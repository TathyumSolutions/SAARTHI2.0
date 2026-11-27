"""
Tests for llm_output_guards: keeping only the usable part of raw model text.

The failing run these cover (Llama 2 7B, supplier on-time-delivery question):
- the simplifier replied with "Sure, I can help ..." plus invented SQL, which
  then steered every later step;
- the SQL generator's "Note: The query is generated ..." and "Explanation:"
  text was glued into the SQL, so the validator reported columns "provided,
  query, specified" and a table called "the".
"""
import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.databridge_services.llm_output_guards import (
    extract_sql,
    sanitize_simplified_query,
)

# ---------------------------------------------------------------------------
# extract_sql
# ---------------------------------------------------------------------------

SQL_WITH_NOTE = (
    "SELECT supplier_id, COUNT(*) AS po_count FROM purchase_orders GROUP BY supplier_id;\n\n"
    "Note: The query is generated based on the information provided in the user query, "
    "and the rules specified in the Strict PostgreSQL query generator."
)

SQL_WITH_EXPLANATION = (
    "SELECT supplier_id, plant_id, plant_name FROM suppliers JOIN plants ON suppliers.plant_id = plants.plant_id;\n"
    "Explanation:\n"
    "* `SELECT`: This keyword tells the database to select specific columns from the table.\n"
    "* `ON suppliers.plant_id = plants.plant_id`: joins rows from the `suppliers` table."
)


def test_trailing_note_is_dropped():
    assert extract_sql(SQL_WITH_NOTE) == (
        "SELECT supplier_id, COUNT(*) AS po_count FROM purchase_orders GROUP BY supplier_id;"
    )


def test_trailing_bullet_explanation_is_dropped():
    sql = extract_sql(SQL_WITH_EXPLANATION)
    assert sql.endswith("plants.plant_id;")
    assert "Explanation" not in sql and "keyword" not in sql


def test_leading_chatter_is_dropped():
    raw = "Sure! Here is the query you asked for:\n\nSELECT * FROM machines LIMIT 5;"
    assert extract_sql(raw) == "SELECT * FROM machines LIMIT 5;"


@pytest.mark.parametrize("lang", ["sql", "SQL", "postgresql", ""])
def test_fenced_block_is_preferred(lang):
    raw = f"Here you go:\n```{lang}\nSELECT status, COUNT(*)\nFROM machines\nGROUP BY status;\n```\nThis groups machines."
    assert extract_sql(raw) == "SELECT status, COUNT(*) FROM machines GROUP BY status;"


def test_cte_statement_is_kept_whole():
    raw = (
        "WITH recent AS (\n  SELECT * FROM purchase_orders WHERE status = 'Received'\n)\n"
        "SELECT supplier_id, COUNT(*) FROM recent GROUP BY supplier_id;\n"
        "This query uses a CTE."
    )
    sql = extract_sql(raw)
    assert sql.startswith("WITH recent AS (")
    assert sql.endswith("GROUP BY supplier_id;")
    assert "CTE" not in sql


def test_semicolon_inside_string_literal_does_not_end_statement():
    raw = "SELECT * FROM suppliers WHERE company_name = 'A; B Ltd' LIMIT 1;\nNote: done"
    assert extract_sql(raw) == "SELECT * FROM suppliers WHERE company_name = 'A; B Ltd' LIMIT 1;"


def test_statement_without_semicolon_stops_at_prose_paragraph():
    raw = "SELECT plant_name\nFROM plants\nWHERE region = 'East'\n\nThis returns every plant in the East region."
    assert extract_sql(raw) == "SELECT plant_name FROM plants WHERE region = 'East'"


def test_blank_line_inside_statement_is_kept_when_sql_continues():
    raw = "SELECT plant_name\nFROM plants\n\nWHERE region = 'East'\nORDER BY plant_name"
    assert extract_sql(raw) == "SELECT plant_name FROM plants WHERE region = 'East' ORDER BY plant_name"


def test_sql_quoted_inside_prose_ends_at_closing_quote():
    raw = '"SELECT supplier_id FROM suppliers JOIN plants ON suppliers.plant_id = plants.plant_id"\n\nExplanation: ...'
    assert extract_sql(raw) == "SELECT supplier_id FROM suppliers JOIN plants ON suppliers.plant_id = plants.plant_id"


def test_sql_comments_and_backticks_are_removed():
    raw = "SELECT `status`, COUNT(*) -- count per status\nFROM machines\nGROUP BY `status`;"
    assert extract_sql(raw) == "SELECT status, COUNT(*) FROM machines GROUP BY status;"


def test_double_quoted_identifiers_are_preserved():
    raw = 'SELECT "Plant Name" FROM plants;'
    assert extract_sql(raw) == 'SELECT "Plant Name" FROM plants;'


def test_statement_with_from_is_preferred_over_earlier_prose_select():
    raw = "I will SELECT the right columns.\nSELECT plant_id FROM plants;"
    assert extract_sql(raw) == "SELECT plant_id FROM plants;"


def test_lowercase_sql_is_accepted():
    assert extract_sql("select count(*) from customers;") == "select count(*) from customers;"


@pytest.mark.parametrize("raw", ["", "   ", None, "I could not find a matching table for this request."])
def test_no_sql_returns_empty(raw):
    assert extract_sql(raw) == ""


def test_extracted_sql_passes_the_validator_that_used_to_fail():
    """The two failing replies from the log, after extraction, contain no
    prose tokens the validator would flag."""
    from app.services.databridge_services.agents.query_validator_agent import QueryValidatorAgent

    schema = {
        "tables": {
            "suppliers": {"columns": {"supplier_id": {}, "plant_id": {}, "supplier_name": {}}},
            "plants": {"columns": {"plant_id": {}, "plant_name": {}}},
            "purchase_orders": {"columns": {"po_id": {}, "supplier_id": {}}},
        }
    }
    validator = QueryValidatorAgent(schema=schema)
    for raw in (SQL_WITH_NOTE, SQL_WITH_EXPLANATION):
        result = validator.validate_generated_sql(extract_sql(raw))
        assert result["status"] == "passed", result


# ---------------------------------------------------------------------------
# sanitize_simplified_query
# ---------------------------------------------------------------------------

ORIGINAL = (
    "For each supplier with at least 3 received POs in the 12 months to 2026-11-27, "
    "what is the on-time delivery percentage? List the 10 lowest with their home plant."
)


def test_simplifier_reply_from_failing_run_is_rejected():
    reply = (
        'Sure, I can help you simplify your query! Here is the simplified query:\n\n'
        '"For each supplier ... list the supplier ID."\n\nSimplified Query:\n\n'
        "SELECT supplier_id FROM production_orders GROUP BY supplier_id;"
    )
    text, reason = sanitize_simplified_query(reply, ORIGINAL)
    assert text == ORIGINAL
    assert reason


@pytest.mark.parametrize("reply", [
    "SELECT * FROM mara LIMIT 5",
    "```sql\nSELECT 1\n```",
    "count machines GROUP BY status",
    "Here is the simplified query: top 5 materials",
    "Certainly - top 5 materials from mara",
    "line one\nline two\nline three\nline four",
    "",
    None,
])
def test_unusable_replies_fall_back_to_original(reply):
    text, reason = sanitize_simplified_query(reply, "top 5 materials from the mara table")
    assert text == "top 5 materials from the mara table"
    assert reason


def test_overlong_reply_falls_back_to_original():
    text, reason = sanitize_simplified_query("word " * 100, "count customers by state")
    assert text == "count customers by state"
    assert reason


@pytest.mark.parametrize("original, reply", [
    ("Can you show me the top 5 materials from the mara table?", "top 5 materials from mara"),
    ("How many machines are there per plant?", "count of machines per plant"),
    ("List 3 customers from kna1", '"3 customers from kna1"'),
])
def test_good_rewrites_are_accepted(original, reply):
    text, reason = sanitize_simplified_query(reply, original)
    assert reason is None
    assert text == reply.strip('"')
