"""
Spreadsheet Table Matching - decides whether a newly uploaded sheet is
"the same table" as one already pushed into the Postgres warehouse (see
spreadsheet_warehouse_service.py), so a re-upload of what's logically the
same data (possibly with renamed/reordered columns) can be appended into
the existing table instead of creating a duplicate one.

Two-stage, cheap-first: a deterministic column-name-overlap score narrows
the field before any LLM call is made at all (most uploads either match
nothing or match nothing worth asking about), then the LLM is only asked
to confirm/refute the shortlisted candidate(s) and propose a rename
mapping for any column that's the same field under a different header -
never to search blind across every table itself. An exact column-name
match skips the LLM call entirely, since that's unambiguous already.

Every LLM output here is treated as an untrusted suggestion, same as
spreadsheet_query_service.py treats its query plans: the confidence/
column_mapping returned are re-validated by the caller
(spreadsheet_warehouse_service.push_table_to_warehouse) against the
candidate table's real schema before anything is written to Postgres.
"""
import json
import os
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.models.spreadsheet_warehouse import SpreadsheetTable
from app.services.llm_call_logger import tracked_invoke

# Below this column-name-overlap score, a table isn't even shown to the
# LLM - not worth the call, and a low-overlap "match" is more likely noise
# than a genuine renamed-column case.
CANDIDATE_THRESHOLD = 0.5
MAX_CANDIDATES = 3


def _normalize(name: str) -> str:
    return (name or "").strip().lower()


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _visible_candidate_tables(connection):
    """Tables this connection's owner could plausibly mean by 'the same
    table' - scoped the same way DatabaseConnection visibility already is
    elsewhere in the app: shared within a company, private to the
    uploading user otherwise. Never includes the connection's own table -
    that's the same-connection re-process case push_table_to_warehouse
    already handles directly, without going through matching at all."""
    query = SpreadsheetTable.query.filter(SpreadsheetTable.connection_id != connection.id)
    if connection.company_code:
        query = query.filter(SpreadsheetTable.company_code == connection.company_code)
    else:
        query = query.filter(
            SpreadsheetTable.company_code.is_(None),
            SpreadsheetTable.created_by_user_id == connection.created_by_user_id,
        )
    return query.all()


def find_candidates(new_columns, connection):
    """Returns [(SpreadsheetTable, score)], sorted best-match first, for
    every existing table whose column-name overlap with new_columns is at
    least CANDIDATE_THRESHOLD - the deterministic pre-filter that runs
    before any LLM call."""
    new_set = {_normalize(c) for c in new_columns}
    scored = []
    for table in _visible_candidate_tables(connection):
        existing_set = {_normalize(c["pg_name"]) for c in (table.column_schema or [])}
        score = _jaccard(new_set, existing_set)
        if score >= CANDIDATE_THRESHOLD:
            scored.append((table, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:MAX_CANDIDATES]


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _build_prompt(new_columns_info, new_display_name: str, candidate: SpreadsheetTable) -> str:
    new_desc = "\n".join(
        f"- {c['name']} ({c['type']}), samples: {c.get('sample_values', [])[:5]}"
        for c in new_columns_info
    )
    existing_desc = "\n".join(
        f"- {c['pg_name']} ({c['type']})" for c in (candidate.column_schema or [])
    )
    return (
        "You are deciding whether a newly uploaded spreadsheet table is the "
        "SAME logical table as an existing one - just possibly with renamed, "
        "reordered, or a subset of columns - as opposed to a genuinely "
        "different dataset that merely happens to share some column names.\n\n"
        f"NEW table \"{new_display_name}\" columns:\n{new_desc}\n\n"
        f"EXISTING table \"{candidate.display_name}\" columns:\n{existing_desc}\n\n"
        "Return ONLY a JSON object of this exact shape, nothing else:\n"
        '{"is_match": true|false, "confidence": 0-100, '
        '"column_mapping": {"<new_column_name>": "<existing_column_name>", ...}}\n\n'
        "column_mapping should include an entry ONLY for a new column whose "
        "name differs from its equivalent existing column but represents the "
        "same field (e.g. \"cust_name\" -> \"customer_name\"). Omit columns "
        "that already match by name. If this is not the same table, set "
        "is_match to false and leave column_mapping empty."
    )


def llm_confirm_match(new_columns_info, new_display_name: str, candidate: SpreadsheetTable,
                       *, company_code=None, user_id=None) -> dict:
    """Asks an LLM to confirm/refute one column-overlap candidate and
    propose a rename mapping. Never trusted blindly - every key/value in
    the returned column_mapping is checked against the actual new/
    candidate column names before being returned, and the caller
    re-validates again before ever using it in an INSERT."""
    prompt = _build_prompt(new_columns_info, new_display_name, candidate)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY"))

    try:
        response = tracked_invoke(
            llm,
            [
                SystemMessage(content="You compare spreadsheet table schemas and respond only with strict JSON."),
                HumanMessage(content=prompt),
            ],
            purpose="spreadsheet.match_confirm", model_name="gpt-4o-mini", provider="openai",
            company_code=company_code, user_id=user_id,
        )
        parsed = _extract_json(response.content)
    except Exception as e:
        print(f"⚠️ [Spreadsheet Matching] LLM confirm failed: {e}")
        parsed = {}

    is_match = bool(parsed.get("is_match"))
    try:
        confidence = max(0, min(100, int(parsed.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0

    existing_names = {c["pg_name"] for c in (candidate.column_schema or [])}
    new_names = {c["name"] for c in new_columns_info}
    raw_mapping = parsed.get("column_mapping") or {}
    column_mapping = {
        k: v for k, v in raw_mapping.items()
        if isinstance(k, str) and isinstance(v, str) and k in new_names and v in existing_names
    }

    return {"is_match": is_match, "confidence": confidence, "column_mapping": column_mapping}


def match_candidates_for_table(new_columns_info, new_display_name: str, connection) -> list:
    """Full two-stage matching pipeline for one uploaded table: cheap
    prefilter, then an LLM confirmation call for each shortlisted
    candidate (skipped entirely for an exact column-set match). Returns a
    list of dicts, best match first, shaped for the 'use existing table'
    checkbox in the UI."""
    new_columns = [c["name"] for c in new_columns_info]
    candidates = find_candidates(new_columns, connection)

    results = []
    for table, score in candidates:
        if score >= 1.0:
            existing_names = {c["pg_name"] for c in (table.column_schema or [])}
            confirmation = {
                "is_match": True,
                "confidence": 100,
                "column_mapping": {c: c for c in new_columns if c in existing_names},
            }
        else:
            confirmation = llm_confirm_match(
                new_columns_info, new_display_name, table,
                company_code=connection.company_code, user_id=connection.created_by_user_id,
            )

        results.append({
            "spreadsheet_table_id": table.id,
            "display_name": table.display_name,
            "pg_table_name": table.pg_table_name,
            "row_count": table.row_count,
            "column_overlap_score": round(score, 2),
            "is_match": confirmation["is_match"],
            "confidence": confirmation["confidence"],
            "column_mapping": confirmation["column_mapping"],
        })

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results
