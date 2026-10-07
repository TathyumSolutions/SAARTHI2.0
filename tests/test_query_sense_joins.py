"""
Tests for QuerySense._validate_plan keeping the LLM's joins/aggregations/
grouping, and for the readable-label augmentation.

_validate_plan used to copy only tables/columns/intent/limit into its
output - joins, aggregations, group_by, filters and order_by always came
out empty. Since SQLGeneratorAgent only joins when the plan's joins list
is non-empty, "Number of employees by branch?" could only ever be answered
as GROUP BY employees.branch_id - a list of opaque ids - never joined to
branches for the branch name.
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.services.databridge_services.agents.query_sense_agent import QuerySenseAgent
from app.services.databridge_services.agents.data_visualizer_agent import DataVisualizerAgent


def _schema(with_fk=False):
    employees_fks = [{"column": "branch_id", "references": "branches.branch_id"}] if with_fk else []
    return {
        "tables": {
            "employees": {
                "description": "Staff",
                "columns": {
                    "employee_id": {"type": "integer"},
                    "first_name": {"type": "character varying"},
                    "branch_id": {"type": "integer"},
                    "salary": {"type": "numeric"},
                },
                "foreign_keys": employees_fks,
            },
            "branches": {
                "description": "Branch master",
                "columns": {
                    "branch_id": {"type": "integer"},
                    "branch_name": {"type": "character varying"},
                    "city": {"type": "character varying"},
                },
                "foreign_keys": [],
            },
            "loans": {
                "description": "Loans",
                "columns": {"loan_id": {"type": "integer"}, "branch_id": {"type": "integer"}, "amount": {"type": "numeric"}},
                "foreign_keys": [],
            },
        },
        "relations": [],
    }


def _qs(schema=None):
    return QuerySenseAgent.QuerySense(schema or _schema(), ollama_model="llama3", ollama_url="http://x")


def _plan(**overrides):
    plan = {
        "tables": ["employees"], "columns": [], "intent": "GROUPED_ANALYSIS",
        "aggregations": [{"function": "count", "column": "*"}],
        "group_by": ["employees.branch_id"], "joins": [],
        "filters": [], "order_by": [], "limit": 0,
    }
    plan.update(overrides)
    return plan


def test_planned_join_survives_validation():
    out = _qs()._validate_plan(_plan(
        tables=["Employees", "Branches"],
        columns=["branches.branch_name"],
        group_by=["employees.branch_id", "branches.branch_name"],
        joins=[{"left": "Employees.Branch_ID", "right": "branches.branch_id"}],
    ))
    assert out["joins"] == [{"left": "employees.branch_id", "right": "branches.branch_id"}]
    assert set(out["tables"]) == {"employees", "branches"}


def test_aggregations_group_by_filters_order_by_are_kept():
    out = _qs()._validate_plan(_plan(
        filters=["employees.salary > 1000"],
        order_by=["count DESC"],
        limit="5",
    ))
    assert out["aggregations"] == [{"function": "count", "column": "*"}]
    assert "employees.branch_id" in out["group_by"]
    assert out["filters"] == ["employees.salary > 1000"]
    assert out["order_by"] == ["count DESC"]
    assert out["limit"] == 5


def test_invented_columns_and_unbacked_joins_are_dropped():
    out = _qs()._validate_plan(_plan(
        group_by=["employees.ghost_col"],
        aggregations=[{"function": "sum", "column": "employees.ghost_col"}],
        filters=["employees.ghost_col = 1"],
        # different column names, no declared/inferred relation -> not a join
        joins=[{"left": "employees.employee_id", "right": "loans.loan_id"}],
    ))
    assert out["joins"] == []
    assert out["group_by"] == []
    assert out["aggregations"] == []
    assert out["filters"] == []
    assert "loans" not in out["tables"]


def test_generic_id_name_match_is_not_a_join():
    schema = _schema()
    schema["tables"]["employees"]["columns"]["id"] = {"type": "integer"}
    schema["tables"]["branches"]["columns"]["id"] = {"type": "integer"}
    out = _qs(schema)._validate_plan(_plan(
        group_by=[], aggregations=[],
        joins=[{"left": "employees.id", "right": "branches.id"}],
    ))
    assert out["joins"] == []


def test_inferred_relation_backs_a_join():
    schema = _schema()
    schema["tables"]["employees"]["columns"]["home_branch"] = {"type": "integer"}
    schema["relations"] = [{"from_table": "employees", "from_column": "home_branch",
                            "to_table": "branches", "to_column": "branch_id"}]
    out = _qs(schema)._validate_plan(_plan(
        group_by=[], aggregations=[],
        joins=[{"left": "employees.home_branch", "right": "branches.branch_id"}],
    ))
    assert out["joins"] == [{"left": "employees.home_branch", "right": "branches.branch_id"}]


def test_grouping_by_fk_id_adds_join_and_readable_name():
    """The screenshot case: the model planned GROUP BY employees.branch_id
    with no join - the validator must add branches.branch_name."""
    for with_fk in (True, False):
        out = _qs(_schema(with_fk=with_fk))._validate_plan(_plan())
        assert out["joins"] == [{"left": "employees.branch_id", "right": "branches.branch_id"}], with_fk
        assert out["group_by"] == ["employees.branch_id", "branches.branch_name"]
        assert "branches.branch_name" in out["columns"]
        assert "branches" in out["tables"]
        assert "loans" not in out["tables"]


def test_label_not_duplicated_when_model_already_planned_it():
    out = _qs()._validate_plan(_plan(
        tables=["employees", "branches"],
        columns=["branches.branch_name"],
        group_by=["employees.branch_id", "branches.branch_name"],
        joins=[{"left": "employees.branch_id", "right": "branches.branch_id"}],
    ))
    assert len(out["joins"]) == 1
    assert out["group_by"].count("branches.branch_name") == 1


def test_grouping_by_tables_own_key_adds_label_without_join():
    out = _qs()._validate_plan(_plan(tables=["branches"], group_by=["branches.branch_id"]))
    assert out["joins"] == []
    assert out["group_by"] == ["branches.branch_id", "branches.branch_name"]


def test_no_label_added_for_non_key_grouping_or_ambiguous_owner():
    # grouping by a plain attribute - nothing to resolve
    out = _qs()._validate_plan(_plan(tables=["branches"], group_by=["branches.city"]))
    assert out["group_by"] == ["branches.city"]

    # employees has only one *_name column but it's first_name - grouping
    # by employee_id adds it (the table's only readable name)...
    out = _qs()._validate_plan(_plan(group_by=["employees.employee_id"]))
    assert out["group_by"] == ["employees.employee_id", "employees.first_name"]

    # ...whereas a table with no readable column gets nothing
    out = _qs()._validate_plan(_plan(tables=["loans"], group_by=["loans.loan_id"]))
    assert out["group_by"] == ["loans.loan_id"]


def test_visualizer_prefers_name_over_id_dimension():
    viz = DataVisualizerAgent.__new__(DataVisualizerAgent)
    rows = [{"branch_id": i, "branch_name": f"Branch {i}", "count": 9} for i in range(1, 30)]
    info = viz._classify_columns(rows, ["branch_id", "branch_name", "count"])
    assert viz._pick_dimension_columns(info, exclude="count")[0] == "branch_name"
