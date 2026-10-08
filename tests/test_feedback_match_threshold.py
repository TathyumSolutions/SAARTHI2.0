"""
Tests for self-learning matching: only LIKED past questions count as a
match, and only at or above the match threshold (80% by default, or the
value in the user's Query Instructions).

Before this, any liked OR disliked question with similarity above 0% was
matched - so a disliked loans question at 25% similarity had its remark
injected into "Number of employees by branch" and was listed in Chain of
Thought / Related Queries as a match.
"""
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
    def __init__(self, question, feedback_type="like", remarks=None, query_code="QUERY00001"):
        self.question = question
        self.answer = "an answer"
        self.feedback_type = feedback_type
        self.remarks = remarks
        self.query_code = query_code


def _run(rows, scores, min_score=DEFAULT_MATCH_THRESHOLD):
    """Runs _build_feedback_context with the DB query and embedder mocked.
    `scores` maps each candidate question to its similarity."""
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value.limit.return_value.all.return_value = rows

    vectors = {q: [i] for i, q in enumerate(scores)}
    embedder = MagicMock()
    embedder.embed_query.side_effect = lambda text: vectors.get(text, ["user_query"])

    with patch.object(router_service, "ResponseFeedback") as fb, \
         patch.object(router_service, "_get_feedback_embedder", return_value=embedder), \
         patch.object(router_service, "_cosine_similarity", side_effect=lambda _a, b: scores[next(q for q, v in vectors.items() if v == b)]):
        fb.query.filter.return_value = query
        result = router_service._build_feedback_context("ACME", 1, "Number of employees by branch", min_score=min_score)
        return result, fb


def test_only_liked_feedback_is_queried():
    _, fb = _run([], {})
    # the SQLAlchemy expression ResponseFeedback.feedback_type == "like"
    fb.feedback_type.__eq__.assert_called_with("like")


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


# ---------------- wiring in get_smart_response ----------------

def test_get_smart_response_passes_threshold_to_both_lookups():
    src = open(os.path.join(ROOT_DIR, "app", "services", "router_service.py")).read()
    assert "match_threshold = match_threshold_from_instructions(system_instructions)" in src
    assert "min_score=max(REUSE_MATCH_THRESHOLD, match_threshold)" in src
    assert "_build_feedback_context(\n                    company_code, user_id, user_query, min_score=match_threshold," in src


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
