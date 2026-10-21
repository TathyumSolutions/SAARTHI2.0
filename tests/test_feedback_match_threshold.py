"""
Tests for self-learning matching: liked AND rejected past questions count
as a match only at or above the match threshold (80% by default, or the
value in the user's Query Instructions).

With no threshold, a disliked loans question at 25% similarity had its
remark injected into "Number of employees by branch". Dropping dislikes
entirely fixed that but meant a rejected answer's remark was never used:
asking "Top 5 plants" again after rejecting it with a correction gave the
same answer. A rejected match above the threshold is now injected as a
correction (remark + rejected SQL), and blocks reusing a liked query.
"""
import datetime
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# The real embedder pulls in sentence-transformers/torch; every test here
# mocks it, so stub the import only when it isn't installed.
try:
    import langchain_huggingface  # noqa: F401
except Exception:
    stub = types.ModuleType("langchain_huggingface")
    stub.HuggingFaceEmbeddings = MagicMock
    sys.modules["langchain_huggingface"] = stub

from app.utils.instruction_settings import match_threshold_from_instructions, DEFAULT_MATCH_THRESHOLD
from app.services import router_service


# ---------------- threshold from Query Instructions ----------------

@pytest.mark.parametrize("instructions, expected", [
    ("", DEFAULT_MATCH_THRESHOLD),
    (None, DEFAULT_MATCH_THRESHOLD),
    ("Query match threshold 90%", 0.90),
    ("Always show currency in USD.\nUse a similarity threshold of 0.85 for related queries.", 0.85),
    ("Only use past queries that match at least 75 percent.", 0.75),
    ("Match threshold 87.5%", 0.875),
    ("Show top 10 in charts. Rank by sales 50% weighted.", DEFAULT_MATCH_THRESHOLD),  # not about matching
    ("Match threshold 150%", DEFAULT_MATCH_THRESHOLD),  # invalid
])
def test_match_threshold_from_instructions(instructions, expected):
    assert match_threshold_from_instructions(instructions) == pytest.approx(expected)


# ---------------- _build_feedback_context ----------------

class _Row:
    def __init__(self, question, feedback_type="like", remarks=None, query_code="QUERY00001",
                 sql_query=None, created_at=None, matched_query_code=None, main_query="SELECT 1"):
        self.question = question
        self.answer = "an answer"
        self.feedback_type = feedback_type
        self.remarks = remarks
        self.query_code = query_code
        self.sql_query = sql_query
        self.created_at = created_at or datetime.datetime(2026, 10, 1)
        self.matched_query_code = matched_query_code
        self.main_query = main_query
        self.router_decision = "DB"


def _run(rows, scores, min_score=DEFAULT_MATCH_THRESHOLD, user_query="Number of employees by branch", logs=()):
    """Runs _build_feedback_context with the DB query and embedder mocked.
    `scores` maps each candidate question to its similarity; `logs` are the
    QueryLog rows a rejected row's main_query is looked up from."""
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value.limit.return_value.all.return_value = rows

    vectors = {q: [i] for i, q in enumerate(scores)}
    embedder = MagicMock()
    embedder.embed_query.side_effect = lambda text: vectors.get(text, ["user_query"])

    with patch.object(router_service, "ResponseFeedback") as fb, \
         patch.object(router_service, "QueryLog") as ql, \
         patch.object(router_service, "_get_feedback_embedder", return_value=embedder), \
         patch.object(router_service, "_cosine_similarity", side_effect=lambda _a, b: scores[next(q for q, v in vectors.items() if v == b)]):
        fb.query.filter.return_value = query
        ql.query.filter.return_value.all.return_value = list(logs)
        result = router_service._build_feedback_context("ACME", 1, user_query, min_score=min_score)
        return result, fb


def test_liked_and_rejected_feedback_are_queried():
    _, fb = _run([], {})
    fb.feedback_type.in_.assert_called_with(("like", "dislike"))


def test_matches_below_threshold_are_dropped():
    rows = [_Row("Total number of loans?", query_code="Q1"),
            _Row("Headcount by branch", query_code="Q2")]
    (context, related), _ = _run(rows, {"Total number of loans?": 0.29, "Headcount by branch": 0.86})
    assert [r["query_code"] for r in related] == ["Q2"]
    assert "Total number of loans" not in context
    assert "LIKED" in context and "DISLIKED" not in context


def test_nothing_above_threshold_gives_no_context():
    rows = [_Row("create a visual for loan count by branch")]
    (context, related), _ = _run(rows, {"create a visual for loan count by branch": 0.25})
    assert context == "" and related == []


def test_custom_threshold_is_respected():
    rows = [_Row("Headcount by branch")]
    (_, related), _ = _run(rows, {"Headcount by branch": 0.86}, min_score=0.9)
    assert related == []
    (_, related), _ = _run(rows, {"Headcount by branch": 0.86}, min_score=0.85)
    assert len(related) == 1


def test_rejected_remark_and_sql_are_injected_for_same_question():
    """The reported bug: "Top 5 plants" rejected with a correction, then asked
    again - the correction and the rejected SQL must reach the prompt."""
    rows = [_Row("Top 5 plants", feedback_type="dislike", query_code="Q9",
                 remarks="Top 5 should be based on networth developed. No need to show ids",
                 sql_query="SELECT plant_id, plant_name FROM plants LIMIT 5")]
    (context, related), _ = _run(rows, {"Top 5 plants": 1.0}, user_query="Top 5 plants")
    assert "REJECTED" in context and "MUST follow" in context
    assert "Top 5 should be based on networth developed. No need to show ids" in context
    assert "SELECT plant_id, plant_name FROM plants LIMIT 5" in context
    assert related == [{"query_code": "Q9", "question": "Top 5 plants", "feedback_type": "dislike",
                         "remarks": "Top 5 should be based on networth developed. No need to show ids",
                         "score": 1.0}]


def test_rejected_sql_falls_back_to_query_log():
    rows = [_Row("Top 5 plants", feedback_type="dislike", query_code="Q9", remarks="rank by net worth")]
    log = MagicMock(query_code="Q9", main_query="SELECT plant_id FROM plants LIMIT 5")
    (context, _), _ = _run(rows, {"Top 5 plants": 0.97}, user_query="top five plants", logs=[log])
    assert "SELECT plant_id FROM plants LIMIT 5" in context


def test_rejected_below_threshold_is_not_injected():
    """Regression guard for the original leak."""
    rows = [_Row("Total number of loans?", feedback_type="dislike", remarks="use loan_amount")]
    (context, related), _ = _run(rows, {"Total number of loans?": 0.25})
    assert context == "" and related == []


def test_corrections_come_before_liked_and_liked_remarks_are_used():
    rows = [_Row("Headcount by branch", query_code="Q1", remarks="show as a bar chart"),
            _Row("Employees per branch", feedback_type="dislike", query_code="Q2", remarks="exclude contractors")]
    (context, related), _ = _run(rows, {"Headcount by branch": 0.9, "Employees per branch": 0.85})
    assert context.index("exclude contractors") < context.index("LIKED")
    assert 'The user noted: "show as a bar chart"' in context
    assert [r["query_code"] for r in related] == ["Q2", "Q1"]


def test_only_newest_feedback_per_query_counts():
    """Rows come newest first: a later like on the same answer supersedes
    the earlier rejection."""
    rows = [_Row("Top 5 plants", feedback_type="like", query_code="Q9"),
            _Row("Top 5 plants", feedback_type="dislike", query_code="Q9", remarks="old complaint")]
    (context, related), _ = _run(rows, {"Top 5 plants": 1.0}, user_query="Top 5 plants")
    assert "old complaint" not in context and "REJECTED" not in context
    assert [r["feedback_type"] for r in related] == ["like"]


# ---------------- wiring in get_smart_response ----------------

def test_get_smart_response_passes_threshold_to_both_lookups():
    src = open(os.path.join(ROOT_DIR, "app", "services", "router_service.py")).read()
    assert "match_threshold = match_threshold_from_instructions(system_instructions)" in src
    assert "min_score=max(REUSE_MATCH_THRESHOLD, match_threshold)" in src
    assert "_build_feedback_context(\n                    company_code, user_id, user_query, min_score=match_threshold," in src


def _find_reusable(rows, scores):
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value.limit.return_value.all.return_value = rows
    embedder = MagicMock()
    embedder.embed_query.side_effect = lambda text: text
    with patch.object(router_service, "QueryLog") as ql, \
         patch.object(router_service, "_get_feedback_embedder", return_value=embedder), \
         patch.object(router_service, "_cosine_similarity", side_effect=lambda _q, text: scores.get(text, 0.0)):
        ql.query.filter.return_value = query
        return router_service._find_reusable_query("ACME", 1, "Top 5 plants")


def test_reuse_skips_liked_query_whose_replay_was_rejected():
    liked = _Row("Top 5 plants", query_code="Q1", created_at=datetime.datetime(2026, 10, 1))
    replay = _Row("Top five plants", feedback_type="dislike", query_code="Q2",
                  matched_query_code="Q1", created_at=datetime.datetime(2026, 10, 2))
    matched, _, _ = _find_reusable([replay, liked], {"Top 5 plants": 1.0, "Top five plants": 0.5})
    assert matched is None


def test_reuse_skips_when_near_duplicate_rejected_after_like():
    liked = _Row("Top 5 plants", query_code="Q1", created_at=datetime.datetime(2026, 10, 1))
    rejected = _Row("Top 5 plants", feedback_type="dislike", query_code="Q3",
                    created_at=datetime.datetime(2026, 10, 3))
    matched, _, _ = _find_reusable([rejected, liked], {"Top 5 plants": 1.0})
    assert matched is None


def test_reuse_still_happens_when_like_is_newer_than_rejection():
    rejected = _Row("Top 5 plants", feedback_type="dislike", query_code="Q3",
                    created_at=datetime.datetime(2026, 10, 1))
    liked = _Row("Top 5 plants", query_code="Q4", created_at=datetime.datetime(2026, 10, 3))
    matched, _, track = _find_reusable([liked, rejected], {"Top 5 plants": 1.0})
    assert matched is liked and track == "DB"


def test_reuse_respects_stricter_threshold():
    """Re-running a liked query's SQL outright uses
    max(REUSE_MATCH_THRESHOLD, user threshold) - never looser than 94%."""
    row = _Row("Number of employees per branch")
    row.router_decision = "DB"
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value.limit.return_value.all.return_value = [row]
    embedder = MagicMock()
    embedder.embed_query.return_value = [1.0]

    with patch.object(router_service, "QueryLog") as ql, \
         patch.object(router_service, "_get_feedback_embedder", return_value=embedder), \
         patch.object(router_service, "_cosine_similarity", return_value=0.95):
        ql.query.filter.return_value = query
        matched, score, track = router_service._find_reusable_query("ACME", 1, "Number of employees by branch")
        assert matched is row and track == "DB"
        matched, _, _ = router_service._find_reusable_query("ACME", 1, "Number of employees by branch", min_score=0.97)
        assert matched is None
