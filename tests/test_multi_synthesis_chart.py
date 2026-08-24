"""
Tests for the MULTI-track synthesizer's chart generation.

Merging tables from different data sources (e.g. a DB aggregate joined
with a Spreadsheet lookup - _merge_tabular_results is already source-
agnostic Python, no LLM involved) only produces a real chart if a
contributing track's own pipeline happened to build one - in practice
that meant only a DB-involving combo ever got charted, since DB is the
only track whose own pipeline runs a visualizer step. A Spreadsheet+API
merge with the exact same column shape got an empty {} instead.

_generate_chart_for_merged_table closes that gap by running the same
deterministic (no LLM call) DataVisualizerAgent directly on the merged
table - "the right code called as per the requirement": _decide_output_
format decides a chart is needed, and if nothing already built one, this
is what actually builds it.
"""
import os
import sys
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services import router_service


def test_empty_table_returns_empty_chart_config_with_no_agent_call():
    with patch("app.services.databridge_services.agents.DataVisualizerAgent") as mocked_agent_cls:
        result = router_service._generate_chart_for_merged_table([], "show net value by group")
    assert result == {}
    mocked_agent_cls.assert_not_called()


def test_generates_chart_from_merged_table_via_data_visualizer_agent():
    """The merged table (columns from whichever tracks contributed) and the
    original user question must reach DataVisualizerAgent exactly as its
    execute(state) contract expects: {data, columns, user_query} in ->
    chart_configs out."""
    merged_table = [
        {"material_group": "MG01", "group_name": "Ferrous Metals", "net_value": 500002.0},
        {"material_group": "MG02", "group_name": "Non-Ferrous Metals", "net_value": 349201.0},
    ]
    fake_chart_configs = {"recommended": "bar", "bar": {"type": "bar"}, "chart_worthy": True}

    mock_agent_instance = MagicMock()
    mock_agent_instance.execute.return_value = {"chart_configs": fake_chart_configs}
    mock_agent_cls = MagicMock(return_value=mock_agent_instance)

    with patch("app.services.databridge_services.agents.DataVisualizerAgent", mock_agent_cls):
        result = router_service._generate_chart_for_merged_table(
            merged_table, "show net value by material group"
        )

    mock_agent_instance.execute.assert_called_once_with({
        "data": merged_table,
        "columns": ["material_group", "group_name", "net_value"],
        "user_query": "show net value by material group",
    })
    assert result == fake_chart_configs


def _run_real_gating_block(primary_result, user_query):
    """Runs the ACTUAL gating code from get_smart_response's MULTI branch
    (extracted verbatim, not reimplemented) against a fake primary_result,
    with _decide_output_format and _generate_chart_for_merged_table
    swapped out - proves the real source's if-condition, not a hand-copy
    of it that could silently drift from the real code."""
    import re
    import textwrap
    src = open(os.path.join(ROOT_DIR, "app", "services", "router_service.py")).read()
    m = re.search(
        r'^ *output_format = _decide_output_format\(primary_result\.get\("table"\)\)\n'
        r'.*?merged_chart = _generate_chart_for_merged_table\(primary_result\.get\("table"\) or \[\], user_query\)\n',
        src, re.S | re.M,
    )
    block = textwrap.dedent(m.group(0))
    ns = {
        "_decide_output_format": router_service._decide_output_format,
        "_generate_chart_for_merged_table": router_service._generate_chart_for_merged_table,
        "primary_result": primary_result,
        "user_query": user_query,
    }
    exec(block, ns)
    return ns["output_format"], ns["merged_chart"]


def test_multi_synthesis_calls_chart_generator_only_when_format_is_chart_and_none_exists():
    """Locks in the gating logic added to the MULTI return path: the chart
    generator only runs when _decide_output_format already said "chart"
    AND no contributing track's own result already had one - never
    unconditionally, and never overriding a chart a track already built."""
    with patch.object(router_service, "_decide_output_format", return_value="chart"), \
         patch.object(router_service, "_generate_chart_for_merged_table", return_value={"bar": {}}) as mocked_gen:
        output_format, merged_chart = _run_real_gating_block(
            {"table": [{"a": 1}], "chart": {}}, "some question"
        )
    mocked_gen.assert_called_once_with([{"a": 1}], "some question")
    assert output_format == "chart"
    assert merged_chart == {"bar": {}}

    # A track that already built a real chart must never be overridden.
    with patch.object(router_service, "_decide_output_format", return_value="chart"), \
         patch.object(router_service, "_generate_chart_for_merged_table") as mocked_gen2:
        output_format, merged_chart = _run_real_gating_block(
            {"table": [{"a": 1}], "chart": {"bar": {"already": "built"}}}, "some question"
        )
    mocked_gen2.assert_not_called()
    assert merged_chart == {"bar": {"already": "built"}}

    # format != "chart" -> generator never runs regardless of existing chart.
    with patch.object(router_service, "_decide_output_format", return_value="table"), \
         patch.object(router_service, "_generate_chart_for_merged_table") as mocked_gen3:
        output_format, merged_chart = _run_real_gating_block(
            {"table": [{"a": 1}], "chart": {}}, "some question"
        )
    mocked_gen3.assert_not_called()
    assert output_format == "table"
    assert merged_chart == {}
