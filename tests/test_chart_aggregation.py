"""Charts must not add up rates/percentages across rows."""
import pytest

from app.services.databridge_services.agents.chart_aggregation import (
    AVG, MAX, MIN, SUM, choose_aggregation, combine, label_for,
)
from app.services.databridge_services.agents.data_visualizer_agent import DataVisualizerAgent


@pytest.mark.parametrize("col,expected", [
    ("interest_rate", AVG),
    ("processing_fee_pct", AVG),
    ("cibil_score", AVG),
    ("npa_share", AVG),
    ("Margin %", AVG),
    ("interest_rate_max", MAX),
    ("max_dpd", MAX),
    ("interest_rate_min", MIN),
    ("disbursed_amount", SUM),
    ("loan_count", SUM),
    ("total_amount", SUM),
])
def test_choose_aggregation(col, expected):
    assert choose_aggregation(col) == expected


def test_combine():
    assert combine([10, 20], AVG) == 15
    assert combine([10, 20], SUM) == 30
    assert combine([10, 20], MAX) == 20
    assert combine([10, 20], MIN) == 10
    assert combine([], AVG) == 0.0


def test_label_for():
    assert label_for("Interest Rate", AVG, aggregated=True) == "Average Interest Rate"
    assert label_for("Interest Rate", AVG, aggregated=False) == "Interest Rate"
    assert label_for("Interest Rate Max", MAX, aggregated=True) == "Interest Rate Max"
    assert label_for("Disbursed Amount", SUM, aggregated=True) == "Disbursed Amount"


def _rows():
    # 100 rows per product, same rate on each row - the screenshot case.
    rows = []
    for name, rate in (("Consumer Durable Loan", 28.0), ("Home Loan", 11.5)):
        rows += [{"product_name": name, "interest_rate_max": rate, "interest_rate": rate - 2}] * 100
    return rows


def test_rate_max_column_is_not_summed():
    viz = DataVisualizerAgent()
    cfg = viz.generate_multiple_chart_configs(_rows(), ["product_name", "interest_rate_max"])
    values = cfg["bar"]["data"]["datasets"][0]["data"]
    assert max(values) == pytest.approx(28.0)
    assert cfg["aggregation"] == MAX


def test_rate_column_is_averaged_and_titled():
    viz = DataVisualizerAgent()
    cfg = viz.generate_multiple_chart_configs(_rows(), ["product_name", "interest_rate"])
    values = cfg["bar"]["data"]["datasets"][0]["data"]
    assert values == pytest.approx([26.0, 9.5])
    assert cfg["bar"]["options"]["plugins"]["title"]["text"].startswith("Average Interest Rate")
    assert "averaged" in cfg["note"]


def test_amounts_still_summed():
    viz = DataVisualizerAgent()
    rows = [{"branch_name": "A", "disbursed_amount": 100.0}, {"branch_name": "A", "disbursed_amount": 50.0},
            {"branch_name": "B", "disbursed_amount": 70.0}]
    cfg = viz.generate_multiple_chart_configs(rows, ["branch_name", "disbursed_amount"])
    assert cfg["bar"]["data"]["datasets"][0]["data"] == pytest.approx([150.0, 70.0])
