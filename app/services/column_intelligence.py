"""
Column intelligence - what each column of a table actually *is*, worked
out from its sample values and, where available, an LLM read of the table.

Every connected table (an uploaded spreadsheet or a real database table)
carries per-column metadata the router, the SQL/spreadsheet planners and
the result combiner all reason over. Name + type + sample values alone
leave too much to guess: a spreadsheet column called "slab_rs_10l_qtr"
holding "0.64%" says nothing about being a percentage commission rate for
the lowest agent-volume slab. This module fills that in, in two layers:

  1. Deterministic, no LLM: numeric text ("0.64%", "1,200", "Rs 5,000")
     becomes real numbers with a recorded unit, and each column gets a
     role - identifier, measure, dimension, date, flag or text - from its
     values (see profile_column).
  2. One LLM call per table (enrich_table_semantics): a business
     description of the table and a one-line meaning for every column,
     grounded in the table's title, original headers, notes and sample
     rows. The answer is validated against the real column list - a
     column the model invents is dropped, never stored.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

ROLES = ("identifier", "measure", "dimension", "date", "flag", "text")
UNITS = ("percent", "currency", "count")

_CURRENCY = r"(?:rs\.?|inr|₹|\$|usd|eur|€|£)"
_NUMERIC_TEXT = re.compile(
    rf"^\s*(?P<cur>{_CURRENCY})?\s*(?P<num>[-+]?(?:\d{{1,3}}(?:,\d{{2,3}})+|\d+)?(?:\.\d+)?)\s*(?P<pct>%)?\s*$",
    re.IGNORECASE,
)
_ID_NAME = re.compile(r"(^|_)(id|code|key|no|number|num|ref)$")
_COUNT_NAME = re.compile(r"(^|_)(count|qty|quantity|cnt)$")
_CURRENCY_NAME = re.compile(r"(amount|amt|price|cost|value|revenue|salary|income|fee|premium|outstanding|balance)")
_PERCENT_NAME = re.compile(r"(pct|percent|rate|ratio|share)")
# Digits that are labels, not quantities - never converted to numbers.
_TEXT_CODE_NAME = re.compile(
    r"(^|_)(code|id|phone|mobile|pin|pincode|zip|postal|account|acct|pan|aadhaar|ifsc)(_|$)"
)
_LEADING_ZERO = re.compile(r"^\s*[-+]?0\d")


def _parse_numeric_text(value: Any) -> Optional[Tuple[float, str]]:
    """("0.64%") -> (0.64, "percent"); ("Rs 1,200") -> (1200.0, "currency");
    ("12") -> (12.0, ""). None if it isn't a number written as text."""
    if not isinstance(value, str):
        return None
    match = _NUMERIC_TEXT.match(value)
    if not match or not re.search(r"\d", match.group("num") or ""):
        return None
    number = float(match.group("num").replace(",", ""))
    if match.group("pct"):
        return number, "percent"
    if match.group("cur"):
        return number, "currency"
    return number, ""


def normalize_numeric_text(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Converts text columns whose every non-empty value is a number written
    as text into real numbers. Percent values keep their percent-point
    value (0.64% -> 0.64) and the column is recorded with unit "percent",
    so arithmetic downstream knows to divide by 100. Returns (df, {column:
    unit}) - a unit only for columns where one was detected.

    Digit strings that are really labels are left alone: a column named
    like a code/ID/phone/PIN/account, or any value with a leading zero
    ("0012" would otherwise silently become 12)."""
    df = df.copy()
    units: Dict[str, str] = {}
    for col in df.columns:
        series = df[col]
        if series.dtype != object:
            continue
        non_null = [v for v in series.tolist() if not (v is None or (isinstance(v, float) and pd.isna(v)))]
        if not non_null or not all(isinstance(v, str) for v in non_null):
            continue
        if not any(v.strip() for v in non_null):
            continue
        if _TEXT_CODE_NAME.search(str(col).lower()) or any(_LEADING_ZERO.match(v) for v in non_null):
            continue
        parsed = [_parse_numeric_text(v) if v.strip() else (None, "") for v in non_null]
        if any(p is None for p in parsed):
            continue
        found_units = {u for _, u in parsed if u}
        if len(found_units) > 1:
            continue
        df[col] = series.map(
            lambda v: (_parse_numeric_text(v) or (None, ""))[0] if isinstance(v, str) and v.strip() else None
        ).astype(float)
        if found_units:
            units[col] = found_units.pop()
    return df, units


def profile_column(name: str, sample_values: list, data_type: str = "",
                   unique_values: Optional[int] = None, row_count: Optional[int] = None,
                   unit: str = "") -> Dict[str, str]:
    """Deterministic role (and unit, when it can tell) for one column, from
    its name, type and sample values. Never calls an LLM."""
    lname = (name or "").lower()
    dtype = (data_type or "").lower()
    samples = [v for v in (sample_values or []) if v is not None]

    is_bool = dtype in ("boolean", "bool") or (samples and all(isinstance(v, bool) for v in samples))
    is_date = any(t in dtype for t in ("date", "time")) or lname.endswith(("_date", "_at", "_on"))
    is_number = (
        dtype in ("number", "integer", "bigint", "smallint", "numeric", "real", "double precision", "decimal")
        or dtype.startswith(("numeric", "decimal", "int", "float"))
        or (samples and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in samples))
    )

    if is_bool:
        return {"role": "flag", "unit": ""}
    if is_date:
        return {"role": "date", "unit": ""}
    if _ID_NAME.search(lname):
        return {"role": "identifier", "unit": ""}
    if is_number:
        if not unit:
            if _COUNT_NAME.search(lname):
                unit = "count"
            elif _PERCENT_NAME.search(lname) and samples and all(abs(float(v)) <= 100 for v in samples):
                unit = "percent"
            elif _CURRENCY_NAME.search(lname):
                unit = "currency"
        return {"role": "measure", "unit": unit}

    if unique_values is not None and row_count and unique_values == row_count and row_count > 1:
        # Every row has its own value - a natural key like a product name.
        texts = [str(v) for v in samples]
        if texts and max(len(t) for t in texts) <= 40:
            return {"role": "identifier", "unit": ""}
    texts = [str(v) for v in samples]
    if texts and sum(len(t) for t in texts) / len(texts) > 60:
        return {"role": "text", "unit": ""}
    return {"role": "dimension", "unit": ""}


def apply_profiles(columns: List[dict], row_count: Optional[int] = None) -> List[dict]:
    """Adds role/unit to every column dict that doesn't already have them.
    Works on both the spreadsheet manifest's columns (type/sample_values)
    and the DB introspection's (data_type/sample_values)."""
    for col in columns or []:
        if not isinstance(col, dict):
            continue
        profile = profile_column(
            col.get("name"), col.get("sample_values") or [],
            col.get("data_type") or col.get("type") or "",
            col.get("unique_values"), row_count, col.get("unit") or "",
        )
        col.setdefault("role", profile["role"])
        if profile["unit"] and not col.get("unit"):
            col["unit"] = profile["unit"]
    return columns


def _semantics_prompt(table_name: str, columns: List[dict], sample_rows: List[dict],
                      title: str = "", notes: str = "", context: str = "") -> str:
    col_lines = []
    for c in columns:
        label = c.get("label")
        samples = ", ".join(str(v) for v in (c.get("sample_values") or [])[:6])
        bits = [f"- {c['name']}"]
        if label and label != c["name"]:
            bits.append(f'original header "{label}"')
        bits.append(f"type {c.get('type') or c.get('data_type') or 'unknown'}")
        if c.get("unit"):
            bits.append(f"unit {c['unit']}")
        if c.get("role"):
            bits.append(f"role {c['role']}")
        if samples:
            bits.append(f"samples: {samples}")
        col_lines.append("; ".join(bits))
    sample_text = "\n".join(json.dumps(r, default=str) for r in sample_rows[:15])
    parts = [f"Table: {table_name}"]
    if title:
        parts.append(f"Title / description written above the table: {title}")
    if context:
        parts.append(f"Description given by whoever connected this data: {context}")
    if notes:
        parts.append(f"Notes written below the table:\n{notes}")
    parts.append("Columns:\n" + "\n".join(col_lines))
    if sample_text:
        parts.append(f"Sample rows:\n{sample_text}")
    parts.append(
        "Work out what this table and each column really mean, using the title, original "
        "headers, notes and the sample values together - not the column name alone. For a "
        "set of banded columns (slabs, tiers, ranges), say what is being banded and where each "
        "column sits in the order (e.g. lowest/highest). Return ONLY a JSON object:\n"
        '{"table_description": "2-3 plain business sentences: what one row is, what it is used for, '
        'and any rule from the notes that changes how the numbers are used",\n'
        ' "columns": {"<column name>": {"meaning": "one short line", "role": "identifier|measure|'
        'dimension|date|flag|text", "unit": "percent|currency|count|"}}}\n'
        "Use only the column names listed above."
    )
    return "\n\n".join(parts)


def _default_llm_invoke(prompt: str) -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage
    from app.services.llm_call_logger import tracked_invoke

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY"))
    response = tracked_invoke(
        llm,
        [SystemMessage(content="You document data tables for business analysts. Output only JSON."),
         HumanMessage(content=prompt)],
        purpose="metamind.column_semantics", model_name="gpt-4o-mini", provider="openai",
    )
    return response.content or ""


def _extract_json_object(text: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enrich_table_semantics(table_name: str, columns: List[dict], sample_rows: List[dict],
                           title: str = "", notes: str = "", context: str = "",
                           llm_invoke=None) -> Dict[str, Any]:
    """One LLM call: {"table_description": str, "columns": {name: {meaning,
    role, unit}}}. Columns the model names that don't exist, and roles/units
    outside the allowed vocabulary, are dropped. Returns {} on any failure -
    callers keep the deterministic profile in that case."""
    known = {c["name"] for c in columns if isinstance(c, dict) and c.get("name")}
    if not known:
        return {}
    try:
        raw = (llm_invoke or _default_llm_invoke)(
            _semantics_prompt(table_name, columns, sample_rows, title, notes, context)
        )
    except Exception as e:
        print(f"⚠️ [COLUMNS] Could not infer column meanings for {table_name}: {e}")
        return {}
    data = _extract_json_object(raw)
    out_columns = {}
    for name, info in (data.get("columns") or {}).items():
        if name not in known or not isinstance(info, dict):
            continue
        entry = {}
        meaning = str(info.get("meaning") or "").strip()
        if meaning:
            entry["meaning"] = meaning[:300]
        if info.get("role") in ROLES:
            entry["role"] = info["role"]
        if info.get("unit") in UNITS:
            entry["unit"] = info["unit"]
        if entry:
            out_columns[name] = entry
    description = str(data.get("table_description") or "").strip()
    return {"table_description": description[:1000], "columns": out_columns}


def merge_semantics(columns: List[dict], semantics: Dict[str, Any]) -> List[dict]:
    """Applies enrich_table_semantics' per-column output onto column dicts.
    The LLM's meaning is always taken; its role/unit only fill gaps or
    override the deterministic guess when the values allow it (a unit is
    never put on a non-numeric column)."""
    by_name = (semantics or {}).get("columns") or {}
    for col in columns or []:
        info = by_name.get(col.get("name"))
        if not info:
            continue
        if info.get("meaning"):
            col["meaning"] = info["meaning"]
        if info.get("role"):
            col["role"] = info["role"]
        if info.get("unit") and col.get("role") == "measure":
            col["unit"] = info["unit"]
    return columns
