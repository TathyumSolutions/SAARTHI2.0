"""
Data Source Finaliser - runs before a question reaches the DB-querying
agents (databridge_services/agents/*) and does two things:

  1. Identify resources: which DB columns in this user's router config
     carry a "lookup_hint" (see automated_metamind._attach_lookup_hints) -
     i.e. columns whose real values are only meaningful through one of
     this user's uploaded spreadsheet lookup tables (region codes,
     material groups, GL account groups, posting keys, ...).
  2. Build a strategy: for each such column, try to resolve a word from
     the question against that lookup table's label columns, and if
     found, resolve it to the lookup table's actual code value(s).

Without this, the SQL-generating agents only ever see the raw question
text and the DB schema - a term like "copper" or "Europe" that's only
defined in a spreadsheet (never as a DB column) gets guessed at, which is
exactly how a hallucinated column (e.g. a nonexistent "region" column) or
a wrong guess makes it into generated SQL. This module resolves the term
deterministically first (a validated pandas lookup, not an LLM guess) and
hands the DB agents a concrete "X resolves to column = value" fact
instead, the same way company_feedback_context is already injected ahead
of the question in updated_router_services.py.

Deliberately no LLM call anywhere in this module - resolution is exact
value/substring matching against small, already-uploaded lookup tables,
so it's fast, free, and never itself a source of hallucination.
"""
import re

from app.services import spreadsheet_service

_STOPWORDS = {
    "the", "a", "an", "in", "on", "for", "of", "to", "and", "or", "is", "are",
    "was", "were", "what", "how", "many", "much", "last", "over", "current",
    "using", "today", "rate", "our", "we", "us", "with", "by", "at", "this",
    "that", "these", "those", "orders", "order", "materials", "material",
    "based", "days", "day", "total", "show", "list", "find",
}


def _candidate_terms(user_query: str) -> list:
    """Lowercased words from the question worth trying against lookup
    tables - short/common words filtered out so a filler word never
    accidentally matches a lookup label. Hyphens split into separate
    words ("copper-based" -> "copper", "based") rather than being kept as
    part of the token, since the compound as a whole almost never appears
    verbatim in a lookup table's label column."""
    words = re.findall(r"[a-zA-Z]+", user_query.lower())
    seen = set()
    terms = []
    for w in words:
        if w in _STOPWORDS or len(w) <= 2 or w in seen:
            continue
        seen.add(w)
        terms.append(w)
    return terms


def _resolve_against_lookup(term: str, lookup_table: str, code_column: str, label_columns: list):
    """
    Looks for `term` inside any of the lookup table's label columns
    (case-insensitive substring match). Returns the distinct matching
    code_column value(s) and which label column/value it matched on, or
    None if nothing matched.
    """
    try:
        df = spreadsheet_service.get_table_df(lookup_table)
    except Exception:
        return None

    if code_column not in df.columns:
        return None

    codes = set()
    matched_on = None
    matched_value = None
    for label_col in label_columns:
        if label_col not in df.columns:
            continue
        mask = df[label_col].astype(str).str.contains(re.escape(term), case=False, na=False)
        matched_rows = df[mask]
        if matched_rows.empty:
            continue
        for _, row in matched_rows.iterrows():
            codes.add(row[code_column])
        if matched_on is None:
            matched_on = label_col
            matched_value = matched_rows.iloc[0][label_col]

    if not codes:
        return None
    return {"codes": sorted(str(c) for c in codes), "matched_on": matched_on, "matched_value": matched_value}


def finalize_data_source_strategy(user_query: str, router_config: dict):
    """
    Entry point. Identifies which DB columns (across this user's visible
    tables) have a lookup_hint, tries to resolve a term from the question
    against each one, and returns a short context block ready to prepend
    to the DB question - or None if there was nothing to resolve (the
    common case: most questions don't involve a coded/looked-up value).
    """
    if not router_config or not user_query:
        return None

    db_tables = (
        router_config.get("routing_menu", {})
        .get("datasources", {})
        .get("DB", {})
        .get("tables", {})
    )
    if not db_tables:
        return None

    terms = _candidate_terms(user_query)
    if not terms:
        return None

    resolved_lines = []
    seen_columns = set()

    for table_name, table_info in db_tables.items():
        for column in table_info.get("columns", []):
            hint = column.get("lookup_hint")
            if not hint:
                continue
            column_key = (table_name, column["name"])
            if column_key in seen_columns:
                continue  # already resolved this column for this question
            seen_columns.add(column_key)

            # Try every candidate term against this column's lookup table -
            # a comparison question ("steel vs. zinc") needs BOTH terms
            # resolved, not just whichever one happens to match first.
            # Stopping at the first match silently drops every other term,
            # leaving the SQL agent to guess a value for it on its own.
            matches = []
            for term in terms:
                result = _resolve_against_lookup(
                    term, hint["lookup_table"], hint["code_column"], hint.get("label_columns", [])
                )
                if result:
                    matches.append((term, result))

            if not matches:
                continue

            parts = [f'"{term}" -> {", ".join(repr(c) for c in r["codes"])}' for term, r in matches]
            resolved_lines.append(
                f'- {table_name}.{column["name"]}: ' + "; ".join(parts) +
                f' (resolved via {hint["lookup_table"]})'
            )

    if not resolved_lines:
        return None

    return (
        "KNOWN CODE TRANSLATIONS (resolved ahead of time from the uploaded lookup "
        "spreadsheets - use these exact columns/values instead of guessing a column "
        "name or inventing one that doesn't exist):\n" + "\n".join(resolved_lines)
    )
