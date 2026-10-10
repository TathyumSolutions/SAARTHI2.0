"""
Result Combiner - joins the tables returned by different data sources for
one question and computes the cross-source figures the question asks for.

Example: "What was the total disbursed amount, and what commission would be
payable if every loan were paid at the lowest slab rate?" The database
returns disbursed amount per product and an uploaded spreadsheet returns
commission slab rates per product. Neither source can answer on its own -
the answer is disbursed x lowest rate, per product, summed. That needs:

  1. Each source's rows in their own DataFrame, cleaned: numbers written as
     text ("0.64%") turned into numbers with their unit, stray note rows
     dropped.
  2. The column the two DataFrames share, found from their VALUES ("Home
     Loan" on both sides), not just from matching column names.
  3. The arithmetic, done by code, not by the answer-writing LLM.

Same safety model as the spreadsheet track (spreadsheet_query_service.py):
the LLM only picks *what* to do as a small JSON plan - which key pair to
join on, which row-wise min/max and which arithmetic to apply - and the
plan is validated against the real columns and the value-verified key
candidates before fixed pandas code runs it. The LLM never supplies code,
and can't invent a join key the data doesn't support. If the plan call
fails or doesn't validate, the tables are still joined on the best
value-verified key, just without derived columns.
"""
import json
import re
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from app.services.column_intelligence import normalize_numeric_text

TRACK_ALIASES = {
    "query_database": "db",
    "query_spreadsheet_data": "sheet",
    "call_external_api": "api",
    "search_documents": "docs",
}
TRACK_LABELS = {
    "query_database": "database",
    "query_spreadsheet_data": "spreadsheet",
    "call_external_api": "external API",
    "search_documents": "documents",
}

ALLOWED_ROW_FUNCS = {"min", "max", "mean", "sum"}
ALLOWED_OPS = {"multiply", "divide", "add", "subtract", "percent_of"}
ALLOWED_JOIN_HOW = {"left", "inner", "outer"}
OP_SYMBOLS = {"multiply": "×", "divide": "÷", "add": "+", "subtract": "−"}
MIN_KEY_OVERLAP = 0.3
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,59}$")


class CombinePlanError(Exception):
    """A combine plan that references a missing column, an unverified join
    key or an operation outside the allowed set. Always caught - the
    deterministic fallback runs instead."""


# ----------------------------------------------------------------------
# 1. One clean DataFrame per source
# ----------------------------------------------------------------------
def _clean_frame(table: list) -> Tuple[pd.DataFrame, Dict[str, str]]:
    df = pd.DataFrame(table)
    if df.empty:
        return df, {}
    df, units = normalize_numeric_text(df)
    if len(df.columns) >= 3:
        # A row with a single filled cell in a 3+ column table is a stray
        # note/footer line ("Notes", "- Commission is paid on..."), not data.
        df = df[df.notna().sum(axis=1) > 1]
    return df.reset_index(drop=True), units


def _norm_key(value) -> Optional[str]:
    """Normalized join value: case, spacing and punctuation ignored, and
    1 / 1.0 / "1" treated as the same key."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    text = re.sub(r"[^0-9a-z]+", " ", str(value).lower()).strip()
    return text or None


def _is_key_like(series: pd.Series) -> bool:
    """Measures (non-integer floats like 8.08e9 or 0.64) are never join keys."""
    non_null = series.dropna()
    if non_null.empty:
        return False
    if pd.api.types.is_float_dtype(series):
        return bool((non_null == non_null.round()).all())
    return True


def _names_related(a: str, b: str) -> bool:
    tokens_a = {t for t in re.split(r"[^a-z0-9]+", a.lower()) if len(t) > 1}
    tokens_b = {t for t in re.split(r"[^a-z0-9]+", b.lower()) if len(t) > 1}
    return bool(tokens_a & tokens_b - {"id", "no", "code", "total", "count"}) or a.lower() == b.lower()


# ----------------------------------------------------------------------
# 2. Find the shared column from the values
# ----------------------------------------------------------------------
def find_key_candidates(left: pd.DataFrame, right: pd.DataFrame, limit: int = 5) -> List[dict]:
    """Every (left column, right column) pair whose normalized values
    actually overlap, best first. overlap = matched distinct values /
    distinct values of the smaller side. A same-named pair with zero
    matching values is never a candidate."""
    candidates = []
    right_sets = {
        col: {k for k in (_norm_key(v) for v in right[col].tolist()) if k}
        for col in right.columns if _is_key_like(right[col])
    }
    for lcol in left.columns:
        if not _is_key_like(left[lcol]):
            continue
        lset = {k for k in (_norm_key(v) for v in left[lcol].tolist()) if k}
        if not lset:
            continue
        for rcol, rset in right_sets.items():
            if not rset:
                continue
            if (pd.api.types.is_numeric_dtype(left[lcol]) and pd.api.types.is_numeric_dtype(right[rcol])
                    and not _names_related(lcol, rcol)):
                # Two plain integer columns (a count and an id, say) share
                # values by coincidence all the time - only trust a numeric
                # pair whose names also point at the same thing.
                continue
            matched = len(lset & rset)
            if not matched:
                continue
            overlap = matched / min(len(lset), len(rset))
            if overlap < MIN_KEY_OVERLAP:
                continue
            same_name = re.sub(r"[^a-z0-9]", "", lcol.lower()) == re.sub(r"[^a-z0-9]", "", rcol.lower())
            right_unique = right[rcol].dropna().map(_norm_key).is_unique
            candidates.append({
                "left_on": lcol, "right_on": rcol,
                "overlap": round(overlap, 3), "matched_values": matched,
                "right_unique": bool(right_unique),
                "_score": overlap + (0.05 if same_name else 0) + (0.05 if right_unique else 0),
            })
    candidates.sort(key=lambda c: c["_score"], reverse=True)
    for c in candidates:
        c.pop("_score", None)
    return candidates[:limit]


# ----------------------------------------------------------------------
# 3. The combine plan: built by the LLM, validated, run by pandas
# ----------------------------------------------------------------------
def _frame_summary(alias: str, label: str, sub_query: str, df: pd.DataFrame, units: dict) -> str:
    cols = []
    for col in df.columns:
        samples = [str(v) for v in df[col].dropna().unique()[:5]]
        unit = f", unit {units[col]}" if units.get(col) else ""
        cols.append(f"  - {col} ({df[col].dtype}{unit}) e.g. {', '.join(samples)}")
    return (f'Table "{alias}" - from the {label}, answering: "{sub_query}" ({len(df)} rows)\n'
            + "\n".join(cols))


def build_plan_prompt(user_query: str, frames: List[dict], candidates: Dict[str, List[dict]]) -> str:
    tables_block = "\n\n".join(
        _frame_summary(f["alias"], f["label"], f["sub_query"], f["df"], f["units"]) for f in frames
    )
    cand_lines = []
    for pair, cands in candidates.items():
        for c in cands:
            cand_lines.append(
                f"- {pair}: {c['left_on']} = {c['right_on']} ({c['matched_values']} shared values, "
                f"overlap {c['overlap']:.0%}{', right side unique' if c['right_unique'] else ''})"
            )
    cand_block = "\n".join(cand_lines) or "(none - these tables share no values)"
    return f"""You combine query results from different data sources into one answer table.
You never write code - only a JSON plan that fixed code will execute.

USER QUESTION: {user_query}

TABLES:
{tables_block}

JOIN KEY CANDIDATES (verified from the actual values - you may ONLY join on one of these):
{cand_block}

Return ONLY a JSON object:
{{
  "joins": [{{"left": "db", "right": "sheet", "left_on": "col", "right_on": "col", "how": "left"}}],
  "row_ops": [{{"as": "new_col", "func": "min", "columns": ["col_a", "col_b"]}}],
  "derived": [{{"as": "new_col", "op": "percent_of", "args": ["amount_col", "rate_col"]}}],
  "totals": ["col_to_sum"],
  "sort_by": {{"column": "col", "ascending": false}},
  "explanation": "one plain sentence describing the combination"
}}

Rules:
- "joins" chains tables one after another; the first join's "left" is the base table (the
  one whose rows the answer is about - usually the one holding the main metric). Use "left"
  unless the question needs only matching rows ("inner"). After a join, a right-table column
  whose name already exists becomes <name>_<right alias>.
- "row_ops" computes a value across several columns of the same row: func min | max | mean | sum
  (e.g. the lowest of several slab/tier rate columns).
- "derived" ops: multiply, divide, add, subtract (args: two column names or numbers), and
  percent_of: args[0] x args[1] / 100, for a column whose unit is percent (e.g. 0.64 meaning
  0.64%). Use percent_of whenever one side is a percent rate.
- Steps run in order: joins, then row_ops, then derived - a later step may use an earlier
  step's "as" column. "as" names must be new snake_case names.
- "totals" lists the numeric columns whose grand total answers the question (e.g. total
  amount, total commission).
- Only use the column names shown above (or produced by an earlier step). Omit any field you
  don't need. If the tables can't be meaningfully combined, return {{"joins": []}}.
"""


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(json)?|```$", "", (text or "").strip()).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise CombinePlanError("The model did not return a combine plan.")
    try:
        plan = json.loads(match.group(0))
    except ValueError as e:
        raise CombinePlanError(f"The combine plan was not valid JSON: {e}")
    if not isinstance(plan, dict):
        raise CombinePlanError("The combine plan was not a JSON object.")
    return plan


def _arg_ok(arg, columns: set) -> bool:
    if isinstance(arg, bool):
        return False
    return isinstance(arg, (int, float)) or (isinstance(arg, str) and arg in columns)


def validate_plan(plan: dict, frames: Dict[str, dict], candidates: Dict[str, List[dict]]) -> dict:
    """Checks every reference in the plan against the real columns, walking
    the steps in order so a later step can use an earlier step's output.
    Join keys must be one of the value-verified candidates."""
    joins = plan.get("joins") or []
    if not isinstance(joins, list):
        raise CombinePlanError("'joins' must be a list.")

    used = []
    columns: set = set()
    for i, join in enumerate(joins):
        left, right = join.get("left"), join.get("right")
        if right not in frames or right in used:
            raise CombinePlanError(f"Join {i + 1} references an unknown or already-joined table '{right}'.")
        if i == 0:
            if left not in frames or left == right:
                raise CombinePlanError(f"Join 1 references an unknown base table '{left}'.")
            used.append(left)
            columns = set(frames[left]["df"].columns)
        elif left not in used:
            raise CombinePlanError(f"Join {i + 1}'s left table '{left}' isn't part of the result yet.")
        pair = f"{left}->{right}"
        allowed = {(c["left_on"], c["right_on"]) for c in candidates.get(pair, [])}
        if (join.get("left_on"), join.get("right_on")) not in allowed:
            raise CombinePlanError(
                f"Join {i + 1} key {join.get('left_on')} = {join.get('right_on')} isn't a verified key for {pair}."
            )
        how = join.get("how") or "left"
        if how not in ALLOWED_JOIN_HOW:
            raise CombinePlanError(f"Join type '{how}' is not allowed.")
        join["how"] = how
        used.append(right)
        renamed = {col: (f"{col}_{right}" if col in columns else col) for col in frames[right]["df"].columns}
        columns |= set(renamed.values())
        if how != "outer" and renamed[join["right_on"]] != join["left_on"]:
            columns.discard(renamed[join["right_on"]])  # dropped after the join (see execute_plan)

    if not joins:
        return plan

    for op in plan.get("row_ops") or []:
        if op.get("func") not in ALLOWED_ROW_FUNCS:
            raise CombinePlanError(f"Row function '{op.get('func')}' is not allowed.")
        cols = op.get("columns") or []
        if not cols or any(c not in columns for c in cols):
            raise CombinePlanError(f"Row op '{op.get('as')}' references a missing column.")
        if not _SAFE_NAME.match(str(op.get("as") or "")) or op["as"] in columns:
            raise CombinePlanError(f"Row op output name '{op.get('as')}' is invalid or already used.")
        columns.add(op["as"])

    for op in plan.get("derived") or []:
        if op.get("op") not in ALLOWED_OPS:
            raise CombinePlanError(f"Operation '{op.get('op')}' is not allowed.")
        args = op.get("args") or []
        if len(args) != 2 or not all(_arg_ok(a, columns) for a in args):
            raise CombinePlanError(f"Derived column '{op.get('as')}' needs two existing columns or numbers.")
        if not _SAFE_NAME.match(str(op.get("as") or "")) or op["as"] in columns:
            raise CombinePlanError(f"Derived column name '{op.get('as')}' is invalid or already used.")
        columns.add(op["as"])

    plan["totals"] = [c for c in (plan.get("totals") or []) if c in columns]
    sort_by = plan.get("sort_by")
    if sort_by and (not isinstance(sort_by, dict) or sort_by.get("column") not in columns):
        plan["sort_by"] = None
    return plan


def _value(df: pd.DataFrame, arg):
    if isinstance(arg, (int, float)) and not isinstance(arg, bool):
        return arg
    return pd.to_numeric(df[arg], errors="coerce")


def execute_plan(plan: dict, frames: Dict[str, dict]) -> Tuple[pd.DataFrame, List[dict]]:
    """Runs a validated plan. Joins happen on normalized key values, so
    "Home Loan" and "home loan " still match. Returns (combined frame, one
    match-stats dict per join)."""
    joins = plan["joins"]
    base = joins[0]["left"]
    df = frames[base]["df"].copy()
    stats = []
    for join in joins:
        right_alias = join["right"]
        right = frames[right_alias]["df"].copy()
        right = right.rename(columns={c: f"{c}_{right_alias}" for c in right.columns if c in df.columns})
        right_on = join["right_on"] if join["right_on"] in right.columns else f"{join['right_on']}_{right_alias}"
        df["__key__"] = df[join["left_on"]].map(_norm_key)
        right["__key__"] = right[right_on].map(_norm_key)
        right = right.dropna(subset=["__key__"]).drop_duplicates(subset=["__key__"])
        left_keys = set(df["__key__"].dropna())
        right_keys = set(right["__key__"])
        df = df.merge(right, on="__key__", how=join["how"]).drop(columns="__key__")
        if join["how"] != "outer" and right_on != join["left_on"]:
            # Same values as the left key on every kept row - just noise.
            df = df.drop(columns=right_on)
        stats.append({
            "left": join["left"], "right": right_alias,
            "left_on": join["left_on"], "right_on": join["right_on"], "how": join["how"],
            "left_rows": len(left_keys), "right_rows": len(right_keys),
            "matched": len(left_keys & right_keys),
            "unmatched_left": sorted(left_keys - right_keys)[:10],
            "unmatched_right": sorted(right_keys - left_keys)[:10],
        })

    for op in plan.get("row_ops") or []:
        block = df[op["columns"]].apply(pd.to_numeric, errors="coerce")
        df[op["as"]] = getattr(block, op["func"])(axis=1)

    for op in plan.get("derived") or []:
        a, b = (_value(df, arg) for arg in op["args"])
        if op["op"] == "multiply":
            df[op["as"]] = a * b
        elif op["op"] == "divide":
            df[op["as"]] = a / b
        elif op["op"] == "add":
            df[op["as"]] = a + b
        elif op["op"] == "subtract":
            df[op["as"]] = a - b
        elif op["op"] == "percent_of":
            df[op["as"]] = a * b / 100

    sort_by = plan.get("sort_by")
    if sort_by:
        df = df.sort_values(by=sort_by["column"], ascending=bool(sort_by.get("ascending", False)))
    return df.reset_index(drop=True), stats


def _fallback_plan(frames: List[dict], candidates: Dict[str, List[dict]]) -> dict:
    """No LLM plan: join every other table onto the base on its best
    value-verified key (left join, base rows kept as they are)."""
    base = frames[0]["alias"]
    joins = []
    for f in frames[1:]:
        cands = candidates.get(f"{base}->{f['alias']}") or []
        if cands:
            best = cands[0]
            joins.append({"left": base, "right": f["alias"], "left_on": best["left_on"],
                          "right_on": best["right_on"], "how": "left"})
    return {"joins": joins}


# ----------------------------------------------------------------------
# Narrative for the strategy / query log
# ----------------------------------------------------------------------
def _fmt(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:,.0f}" if abs(number) >= 1000 else f"{number:,.4g}"


def _describe_arg(arg) -> str:
    return _fmt(arg) if isinstance(arg, (int, float)) else arg


def describe_combination(frames: Dict[str, dict], plan: dict, stats: List[dict], totals: dict,
                         notes: List[str]) -> str:
    parts = []
    for f in frames.values():
        parts.append(f'{f["label"]} "{f["sub_query"]}" ({len(f["df"])} rows)')
    text = "Combined " + " with ".join(parts) + "."
    for s in stats:
        text += (
            f" Joined {frames[s['left']]['label']}.{s['left_on']} to {frames[s['right']]['label']}.{s['right_on']}"
            f" ({s['how']} join, {s['matched']} of {s['left_rows']} {frames[s['left']]['label']} values matched)."
        )
    for op in plan.get("row_ops") or []:
        text += f" {op['as']} = {op['func']} of ({', '.join(op['columns'])})."
    for op in plan.get("derived") or []:
        a, b = (_describe_arg(x) for x in op["args"])
        formula = f"{a} × {b} ÷ 100" if op["op"] == "percent_of" else f"{a} {OP_SYMBOLS[op['op']]} {b}"
        text += f" {op['as']} = {formula}."
    if totals:
        text += " Totals: " + "; ".join(f"{k} = {_fmt(v)}" for k, v in totals.items()) + "."
    if notes:
        text += " " + " ".join(notes)
    return text


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def combine_results(ok_results: list, user_query: str,
                    llm_invoke: Optional[Callable[[str], str]] = None) -> Optional[dict]:
    """ok_results: [(track_name, result), ...] from the router. Returns None
    when fewer than two tracks returned rows (nothing to combine).
    Otherwise {"base": track name of the base table, "table": combined
    rows, "totals": {col: grand total}, "plan": the plan that ran,
    "join_stats": [...], "notes": [...], "strategy": plain-language
    description, "planned_by": "llm" | "fallback"}."""
    frames_list = []
    for name, result in ok_results:
        if not result.get("table"):
            continue
        df, units = _clean_frame(result["table"])
        if df.empty:
            continue
        alias = TRACK_ALIASES.get(name, re.sub(r"[^a-z0-9]", "", name.lower())[:10] or "src")
        while any(f["alias"] == alias for f in frames_list):
            alias += "2"
        frames_list.append({
            "name": name, "alias": alias, "label": TRACK_LABELS.get(name, name),
            "sub_query": result.get("child_query") or user_query, "df": df, "units": units,
        })
    if len(frames_list) < 2:
        return None

    # The table holding the question's main metric is usually the DB's -
    # keep it as the base so its rows (and their order) survive the join.
    priority = {"query_database": 0, "query_spreadsheet_data": 1}
    frames_list.sort(key=lambda f: priority.get(f["name"], 2))
    frames = {f["alias"]: f for f in frames_list}

    candidates = {}
    for a in frames_list:
        for b in frames_list:
            if a is not b:
                cands = find_key_candidates(a["df"], b["df"])
                if cands:
                    candidates[f"{a['alias']}->{b['alias']}"] = cands

    plan, planned_by, notes = None, "fallback", []
    if llm_invoke and candidates:
        try:
            raw = llm_invoke(build_plan_prompt(user_query, frames_list, candidates))
            plan = validate_plan(_extract_json(raw), frames, candidates)
            planned_by = "llm"
        except Exception as e:
            print(f"⚠️ [COMBINER] Plan rejected, falling back to a plain key join: {e}")
            plan = None
    if not plan or not plan.get("joins"):
        plan = validate_plan(_fallback_plan(frames_list, candidates), frames, candidates)
        planned_by = "fallback"

    if not plan["joins"]:
        base = frames_list[0]
        for other in frames_list[1:]:
            notes.append(
                f"Could not align the {other['label']} result with the {base['label']} result: they share "
                f"no matching values in any column, so the two could NOT be cross-referenced. Do not treat "
                f"any {base['label']} column as a stand-in for the {other['label']} data."
            )
        return {
            "base": base["name"], "table": json.loads(base["df"].to_json(orient="records", date_format="iso")),
            "totals": {}, "plan": plan, "join_stats": [], "notes": notes, "planned_by": planned_by,
            "strategy": describe_combination(frames, plan, [], {}, notes),
        }

    combined, stats = execute_plan(plan, frames)
    joined = {plan["joins"][0]["left"]} | {j["right"] for j in plan["joins"]}
    for f in frames_list:
        if f["alias"] not in joined:
            notes.append(f"The {f['label']} result shares no matching values with the rest, so it was not joined.")
    for s in stats:
        if s["matched"] < s["left_rows"]:
            notes.append(
                f"{s['left_rows'] - s['matched']} {frames[s['left']]['label']} value(s) had no match in the "
                f"{frames[s['right']]['label']} (e.g. {', '.join(s['unmatched_left'][:3])}) - their combined "
                f"figures are empty."
            )

    totals = {}
    for col in plan.get("totals") or []:
        values = pd.to_numeric(combined[col], errors="coerce")
        if values.notna().any():
            totals[col] = round(float(values.sum()), 2)

    return {
        "base": frames[plan["joins"][0]["left"]]["name"],
        "table": json.loads(combined.to_json(orient="records", date_format="iso")),
        "totals": totals, "plan": plan, "join_stats": stats, "notes": notes, "planned_by": planned_by,
        "strategy": describe_combination(frames, plan, stats, totals, notes),
    }
