"""The safety row cap must be detected and disclosed, not silently applied."""
import pandas as pd

from app.services.databridge_services.agents.insight_rules import build_insight_rules
from app.services.databridge_services.agents.result_cap import (
    ROW_CAP, apply_row_cap, trim_to_cap, truncation_note,
)
from app.services.databridge_services.langgraph_agent import _compose_final_answer


def test_cap_fetches_one_probe_row():
    sql, applied = apply_row_cap("SELECT * FROM loans")
    assert applied and sql.endswith(f"LIMIT {ROW_CAP + 1};")


def test_query_with_own_limit_untouched():
    sql, applied = apply_row_cap("SELECT * FROM loans LIMIT 5")
    assert not applied and sql == "SELECT * FROM loans LIMIT 5"
    _, applied = apply_row_cap("SELECT * FROM loans FETCH FIRST 5 ROWS ONLY")
    assert not applied


def test_trim_detects_truncation():
    df, truncated = trim_to_cap(pd.DataFrame({"a": range(ROW_CAP + 1)}), cap_applied=True)
    assert truncated and len(df) == ROW_CAP


def test_trim_full_result_not_truncated():
    df, truncated = trim_to_cap(pd.DataFrame({"a": range(ROW_CAP)}), cap_applied=True)
    assert not truncated and len(df) == ROW_CAP


def test_insight_rules_mention_sample_only_when_truncated():
    assert "sample" in build_insight_rules(True, ROW_CAP)
    assert "sample" not in build_insight_rules(False, 10)
    assert "Insights must answer the User Query" in build_insight_rules(False, 10)


def test_final_answer_discloses_truncation():
    state = {"format": "chart", "columns": ["product_name", "fee"], "row_count": ROW_CAP,
             "result_truncated": True, "insights": []}
    answer = _compose_final_answer(state)
    assert truncation_note(ROW_CAP) in answer


def test_state_schema_keeps_honesty_fields():
    from app.services.databridge_services.agent_state import DataBridgeState
    assert "result_truncated" in DataBridgeState.__annotations__
    assert "assumption_note" in DataBridgeState.__annotations__
