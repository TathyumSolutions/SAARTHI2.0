"""
Tests for two answer-quality fixes, from "How many machines have had
breakdowns?" (answered on GPT-4o):

1. Counting: the plan counted downtime ROWS - COUNT(machine_downtime.
   machine_id) = 1749 events, scheduled maintenance included - instead of
   distinct machines with a breakdown. QuerySense can now plan
   count_distinct, sees each category column's values (so "breakdowns" can
   become a downtime_category filter), and the SQL generator is told what
   count_distinct and the filters list mean.
2. Single figure: the one-row answer got a one-point line chart and LLM
   "insights" about a NaN standard deviation. One row is now stated
   plainly, with no chart and no insight LLM call.
"""
import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.databridge_services.agents.data_insight_generator_agent import DataInsightGeneratorAgent
from app.services.databridge_services.agents.data_visualizer_agent import DataVisualizerAgent
from app.services.databridge_services.agents.query_sense_agent import (
    PLAN_JSON_SCHEMA,
    QuerySenseAgent,
    _category_values,
)
from app.services.databridge_services.langgraph_agent import _compose_final_answer
from app.services.databridge_services.result_summary import (
    SINGLE_FIGURE_CHART_NOTE,
    summarize_single_row,
)


def _schema():
    return {
        "tables": {
            "machines": {
                "description": "Machine master",
                "columns": {
                    "machine_id": {"type": "integer", "role": "identifier", "meaning": "Machine id",
                                   "example_values": [1, 2, 3]},
                    "machine_name": {"type": "character varying", "role": "identifier",
                                     "example_values": ["CNC Lathe #3"]},
                    "status": {"type": "character varying", "role": "dimension", "meaning": "Current status",
                               "example_values": ["Running", "Running", "Under Maintenance"]},
                },
                "foreign_keys": [],
            },
            "machine_downtime": {
                "description": "One row per downtime event",
                "columns": {
                    "downtime_id": {"type": "bigint", "role": "identifier", "example_values": [1, 2]},
                    "machine_id": {"type": "integer", "role": "identifier", "example_values": [1, 2, 3, 3]},
                    "downtime_category": {"type": "character varying", "role": "dimension",
                                          "meaning": "Type of downtime event",
                                          "example_values": ["Minor Breakdown", "Scheduled Maintenance",
                                                             "Scheduled Maintenance", "Major Breakdown"]},
                    "downtime_hours": {"type": "numeric", "role": "measure", "example_values": ["6.83"]},
                },
                "foreign_keys": [{"column": "machine_id", "references": "machines.machine_id"}],
            },
        },
        "relations": [],
    }


def _qs():
    return QuerySenseAgent.QuerySense(_schema(), ollama_model="llama3", ollama_url="http://x")


# ---------------------------------------------------------------- counting

def test_plan_schema_allows_count_distinct():
    fn_schema = PLAN_JSON_SCHEMA["properties"]["aggregations"]["items"]["properties"]["function"]
    assert "count_distinct" in fn_schema["enum"]


def test_validate_plan_keeps_count_distinct_and_filters():
    plan = {
        "tables": ["machine_downtime"], "columns": [], "intent": "AGGREGATION",
        "aggregations": [{"function": "count_distinct", "column": "machine_downtime.machine_id"}],
        "group_by": [], "joins": [],
        "filters": ["machine_downtime.downtime_category ILIKE '%breakdown%'"],
        "order_by": [], "limit": 0, "assumption_note": "",
    }
    out = _qs()._validate_plan(plan)
    assert out["aggregations"] == [{"function": "count_distinct", "column": "machine_downtime.machine_id"}]
    assert out["filters"] == ["machine_downtime.downtime_category ILIKE '%breakdown%'"]


def test_category_values_are_distinct_and_only_for_dimensions():
    cols = _schema()["tables"]["machine_downtime"]["columns"]
    assert _category_values(cols["downtime_category"]) == [
        "Minor Breakdown", "Scheduled Maintenance", "Major Breakdown"]
    assert _category_values(cols["machine_id"]) == []
    assert _category_values(cols["downtime_hours"]) == []
    assert _category_values({"role": "dimension", "example_values": [None, "", "x" * 80]}) == []


def test_schema_context_shows_meanings_and_category_values():
    text = _qs()._schema_context_text()
    assert ("machine_downtime.downtime_category: Type of downtime event "
            "(values: Minor Breakdown, Scheduled Maintenance, Major Breakdown)") in text
    assert "machines.status: Current status (values: Running, Under Maintenance)" in text
    assert "machine_downtime.machine_id: (values" not in text


def test_planner_prompt_carries_counting_and_filter_rules():
    qs = _qs()
    qs.openai_key = "test-key"
    with patch("app.services.databridge_services.agents.query_sense_agent.tracked_invoke",
               return_value=MagicMock(content="{}")) as mocked_invoke:
        qs._call_llm_for_plan("How many machines have had breakdowns?", "gpt-4o-mini")
    prompt = mocked_invoke.call_args.args[1]
    assert "COUNT THINGS, NOT ROWS" in prompt
    assert "QUALIFYING WORDS ARE FILTERS" in prompt
    assert "values: Minor Breakdown" in prompt


def test_sql_generator_prompt_explains_count_distinct():
    from app.services.databridge_services.agents.sql_generator_agent import SQLGeneratorAgent

    agent = SQLGeneratorAgent(llm_backend={"url": "http://x", "model": "llama3"})
    captured = {}

    def fake_invoke(llm, prompt, **kwargs):
        captured["prompt"] = prompt
        return MagicMock(content="SELECT 1 FROM machines;")

    with patch("app.services.databridge_services.agents.sql_generator_agent.tracked_invoke",
               side_effect=fake_invoke):
        agent.openai_key = "test-key"
        agent.generate_sql_from_querysense("q", {"tables": ["machines"]}, "q", target_model="gpt-4o-mini")
    assert "COUNT(DISTINCT <column>)" in captured["prompt"]
    assert '"filters" list in the WHERE' in captured["prompt"]


# ----------------------------------------------------------- single figure

@pytest.mark.parametrize("row, expected", [
    ({"count": 1749}, "Count: 1,749."),
    ({"total_amount": Decimal("3962672.74")}, "Total amount: 3,962,672.74."),
    ({"avg_hours": 5.0}, "Avg hours: 5."),
    ({"avg_hours": 5.1234}, "Avg hours: 5.12."),
    ({"total": "1,234"}, "Total: 1,234."),
    ({"top_plant": "Durgapur Plant 1", "orders": 12}, "Top plant: Durgapur Plant 1; Orders: 12."),
    ({"value": None}, "Value: no value."),
    ({"value": float("nan")}, "Value: no value."),
    ({"code": "PO00000001"}, "Code: PO00000001."),
])
def test_summarize_single_row(row, expected):
    assert summarize_single_row(row) == expected


def test_single_row_insights_skip_the_llm():
    agent = DataInsightGeneratorAgent()
    with patch("requests.post", side_effect=AssertionError("LLM must not be called")), \
         patch("app.services.databridge_services.agents.data_insight_generator_agent.tracked_invoke",
               side_effect=AssertionError("LLM must not be called")):
        out = agent.generate_insights([{"count": 1749}], ["count"], "How many machines?",
                                      target_model="api://gpt-4o")
    assert out == {"insights": ["Count: 1,749."], "visualizations": []}


def test_single_row_is_not_charted():
    viz = DataVisualizerAgent()
    out = viz.generate_multiple_chart_configs([{"count": 1749}], ["count"])
    assert out["chart_worthy"] is False
    assert out["note"] == SINGLE_FIGURE_CHART_NOTE
    assert out["line"] == {} and out["bar"] == {}


def test_two_rows_are_still_charted():
    viz = DataVisualizerAgent()
    data = [{"status": "Running", "count": 10}, {"status": "Idle", "count": 3}]
    assert viz.generate_multiple_chart_configs(data, ["status", "count"])["chart_worthy"] is True


def test_final_answer_for_single_figure_is_the_value():
    state = {
        "format": "kpi", "columns": ["count"], "row_count": 1, "data": [{"count": 1749}],
        "chart_configs": {"note": SINGLE_FIGURE_CHART_NOTE},
        "insights": ["There is no variability in the data as the standard deviation is NaN."],
    }
    assert _compose_final_answer(state) == "Count: 1,749."


def test_final_answer_keeps_assumption_note_for_single_figure():
    state = {"format": "kpi", "columns": ["count"], "row_count": 1, "data": [{"count": 7}],
             "assumption_note": "No 'revenue' column; counted orders instead."}
    assert _compose_final_answer(state) == "Note: No 'revenue' column; counted orders instead. Count: 7."


def test_final_answer_for_many_rows_is_unchanged():
    state = {"format": "table", "columns": ["status", "count"], "row_count": 2,
             "data": [{"status": "a", "count": 1}, {"status": "b", "count": 2}],
             "chart_configs": {"note": "Grouped."}, "insights": ["b leads."]}
    assert _compose_final_answer(state).startswith("Retrieved 2 rows across 2 columns")
