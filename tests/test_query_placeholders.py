"""Tests for filling ":name" placeholders left in a user's question."""
import os
import sys
from datetime import date

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.query_placeholders import (
    build_missing_value_question,
    resolve_query_placeholders,
)

TODAY = date(2026, 11, 27)


def test_as_of_from_failing_question_becomes_today():
    q = "For each supplier with at least 3 received POs in the 12 months to :as_of, what is the on-time %?"
    res = resolve_query_placeholders(q, today=TODAY)
    assert res.text == q.replace(":as_of", "2026-11-27")
    assert res.resolved == {"as_of": "2026-11-27"}
    assert res.unresolved == []


@pytest.mark.parametrize("name", [
    "asof", "as_of_date", "today", "now", "start_date", "end_date", "from_date",
    "to_date", "period_end", "report_date", "date", "cutoff", "date_from", "invoice_date",
])
def test_date_like_names_are_filled(name):
    res = resolve_query_placeholders(f"sales up to :{name}", today=TODAY)
    assert res.text == "sales up to 2026-11-27"
    assert res.unresolved == []


def test_non_date_placeholders_are_reported_once_in_order():
    res = resolve_query_placeholders("orders for :plant and :supplier at :plant", today=TODAY)
    assert res.text == "orders for :plant and :supplier at :plant"
    assert res.unresolved == ["plant", "supplier"]


def test_mixed_placeholders():
    res = resolve_query_placeholders("downtime at :plant until :as_of", today=TODAY)
    assert res.text == "downtime at :plant until 2026-11-27"
    assert res.unresolved == ["plant"]


@pytest.mark.parametrize("q", [
    "shifts starting at 10:30",
    "cast it with created_at::date",
    "see http://example.com/api",
    "Note:check the totals",
    "ratio 3:1 of rejects",
    "show machines :)",
    "Status: Running machines",
    "",
])
def test_text_without_placeholders_is_unchanged(q):
    res = resolve_query_placeholders(q, today=TODAY)
    assert res.text == q
    assert res.resolved == {} and res.unresolved == []


def test_placeholder_at_start_of_text():
    res = resolve_query_placeholders(":today orders", today=TODAY)
    assert res.text == "2026-11-27 orders"


def test_missing_value_question_names_each_placeholder():
    msg = build_missing_value_question(["plant", "supplier"])
    assert ":plant" in msg and ":supplier" in msg
