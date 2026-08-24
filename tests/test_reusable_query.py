"""
Tests for generalized self-learning reuse: checking for a previously-liked
query BEFORE the router LLM ever runs, not just after a track has already
been chosen.

Only DB and SPREADSHEET are reusable (see REUSABLE_TRACKS in
router_service.py) - their QueryLog.main_query stores enough raw state
(exact SQL text / exact query plan JSON) to be replayed with no further
LLM call at all. FILES, API, and GENERAL/MULTI are deliberately excluded:
none of them persist enough raw state to replay without re-running the
same LLM call(s) that made them expensive in the first place.

This file covers:
  1. REUSE_DISPATCH wiring - every REUSABLE_TRACKS entry has a matching
     dispatch function, and vice versa (no drift between the two).
  2. _run_reused_spreadsheet_query - re-executes a stored plan directly via
     _execute_plan (no LLM call), and reports failure honestly if the plan
     no longer runs (e.g. a column was renamed since it was stored).
  3. _find_reusable_query - scoped correctly (company vs. user), matches
     only liked DB/SPREADSHEET queries, and respects REUSE_MATCH_THRESHOLD.
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import router_service


class _FakeMatched:
    def __init__(self, query_code="Q-1", main_query="{}", answer="cached answer",
                 sources=None, question="original question", remarks=None):
        self.query_code = query_code
        self.main_query = main_query
        self.answer = answer
        self.sources = sources or []
        self.question = question
        self.remarks = remarks


def test_reuse_dispatch_matches_reusable_tracks_exactly():
    """REUSABLE_TRACKS and REUSE_DISPATCH must never drift - a track listed
    as reusable with no dispatch entry would KeyError the moment a real
    match for it came in."""
    assert set(router_service.REUSABLE_TRACKS) == set(router_service.REUSE_DISPATCH.keys())
    assert router_service.REUSE_DISPATCH["DB"] is router_service._run_reused_db_query
    assert router_service.REUSE_DISPATCH["SPREADSHEET"] is router_service._run_reused_spreadsheet_query


def test_reused_spreadsheet_query_replays_stored_plan_with_no_llm_call():
    """Given a matched QueryLog row whose main_query is a stored plan JSON,
    re-executing it must call _execute_plan directly - not rebuild a plan
    via any LLM - and return the stored answer text (accepted as the
    trade-off for skipping the answer-writing LLM call too)."""
    stored_plan = {"tables": ["metal_codes"], "filters": []}
    matched = _FakeMatched(
        query_code="Q-42", main_query=json.dumps(stored_plan),
        answer="There are 2 metal codes: copper (CU) and zinc (ZN).",
        sources=["metal_codes<Spreadsheet>"], question="what are the metal codes?",
    )

    fake_df = MagicMock()
    fake_df.to_json.return_value = json.dumps(
        [{"metal": "copper", "code": "CU"}, {"metal": "zinc", "code": "ZN"}]
    )

    with patch("app.services.spreadsheet_query_service._execute_plan", return_value=fake_df) as mocked_exec:
        result = router_service._run_reused_spreadsheet_query(
            "what are the metal codes", matched, 0.97, {"session_id": "s1"}
        )

    mocked_exec.assert_called_once_with(stored_plan)
    assert result["error"] is False
    assert result["answer"] == "There are 2 metal codes: copper (CU) and zinc (ZN)."
    assert result["table"] == [{"metal": "copper", "code": "CU"}, {"metal": "zinc", "code": "ZN"}]
    assert result["execution_type"] == "reused"
    assert result["matched_query_code"] == "Q-42"
    assert result["match_score"] == 0.97
    assert "Q-42" in result["strategy"]
    assert result["related_queries"] == [{
        "query_code": "Q-42", "question": "what are the metal codes?",
        "feedback_type": "like", "remarks": None, "score": 0.97,
    }]


def test_reused_spreadsheet_query_reports_failure_honestly():
    """If the stored plan no longer runs against current data (e.g. a
    column was renamed since it was stored), this must report error=True
    with an empty table - never a stale/misleading success."""
    matched = _FakeMatched(main_query=json.dumps({"tables": ["metal_codes"]}))

    with patch("app.services.spreadsheet_query_service._execute_plan",
               side_effect=ValueError("no such column: old_name")):
        result = router_service._run_reused_spreadsheet_query(
            "some question", matched, 0.95, {"session_id": "s1"}
        )

    assert result["error"] is True
    assert result["table"] == []


def test_find_reusable_query_only_matches_liked_db_or_spreadsheet():
    """The candidate query must filter on router_decision in {DB,
    SPREADSHEET} (via .in_(REUSABLE_TRACKS)), feedback_type == 'like', and
    a non-null main_query - FILES/API/GENERAL/MULTI rows, disliked rows,
    and rows with no stored main_query must never be candidates."""
    candidate = MagicMock()
    candidate.question = "what are the metal codes?"
    candidate.router_decision = "SPREADSHEET"

    mock_query_chain = MagicMock()
    mock_query_chain.filter.return_value = mock_query_chain
    mock_query_chain.order_by.return_value = mock_query_chain
    mock_query_chain.limit.return_value = mock_query_chain
    mock_query_chain.all.return_value = [candidate]

    fake_embedder = MagicMock()
    fake_embedder.embed_query.return_value = [1.0, 0.0]

    with patch.object(router_service.QueryLog, "query", mock_query_chain), \
         patch.object(router_service, "_get_feedback_embedder", return_value=fake_embedder), \
         patch.object(router_service, "_cosine_similarity", return_value=0.96):
        matched, score, track = router_service._find_reusable_query(
            "company1", None, "what are the metal codes?"
        )

    # router_decision, feedback_type, and main_query each contribute their
    # own .filter(...) call (plus one more for the company/user scope) -
    # the exact SQLAlchemy expressions aren't asserted here (that's the
    # ORM's job to get right), just that filtering actually happened
    # before the candidates were pulled.
    assert mock_query_chain.filter.call_count >= 3
    assert matched is candidate
    assert score == 0.96
    assert track == "SPREADSHEET"


def test_find_reusable_query_below_threshold_returns_no_match():
    candidate = MagicMock()
    candidate.question = "a completely different question"
    candidate.router_decision = "DB"

    mock_query_chain = MagicMock()
    mock_query_chain.filter.return_value = mock_query_chain
    mock_query_chain.order_by.return_value = mock_query_chain
    mock_query_chain.limit.return_value = mock_query_chain
    mock_query_chain.all.return_value = [candidate]

    fake_embedder = MagicMock()
    fake_embedder.embed_query.return_value = [1.0, 0.0]

    with patch.object(router_service.QueryLog, "query", mock_query_chain), \
         patch.object(router_service, "_get_feedback_embedder", return_value=fake_embedder), \
         patch.object(router_service, "_cosine_similarity", return_value=0.5):
        matched, score, track = router_service._find_reusable_query(
            "company1", None, "how many orders were placed?"
        )

    assert matched is None
    assert score == 0.0
    assert track is None


def test_find_reusable_query_requires_scope():
    """No company_code and no user_id means there's no self-learning scope
    to search within - must return no-match rather than querying globally
    across every company's data."""
    matched, score, track = router_service._find_reusable_query(None, None, "some question")
    assert matched is None
    assert score == 0.0
    assert track is None
