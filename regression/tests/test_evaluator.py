"""Unit tests for the value-based grading (no database, no LLM)."""
from regression.bank import Question
from regression.evaluator import ERROR, FAIL, PARTIAL, PASS, grade
from regression.pipeline_runner import PipelineOutcome
from regression.reference import ResultSet


def _q(mode="set", match=None, **extra):
    compare = {"mode": mode, **({"match_columns": match} if match else {}), **extra}
    return Question(id="X", domain="d", category="simple", sources=["DB"], question="?",
                    reference_sql="SELECT 1", compare=compare)


def _out(columns, rows, message="", error=None):
    return PipelineOutcome(question_id="X", columns=columns, rows=rows, message=message, error=error)


EXPECTED = ResultSet(columns=["region", "active_branches"], rows=[["North", 2], ["South", 8], ["West", 5]])


def test_set_match_ignores_column_names_and_order():
    out = _out(["Region Name", "cnt"], [["south", 8], ["West", 5], ["North", 2]])
    assert grade(_q(match=["region", "active_branches"]), EXPECTED, out).status == PASS


def test_wrong_count_is_partial():
    out = _out(["region", "n"], [["North", 2], ["South", 9], ["West", 5]])
    v = grade(_q(match=["region", "active_branches"]), EXPECTED, out)
    assert v.status == PARTIAL and v.missing_columns == ["active_branches"]


def test_extra_rows_fail_row_count():
    out = _out(["region", "n"], [["North", 2], ["South", 8], ["West", 5], ["East", 1]])
    assert grade(_q(match=["region", "active_branches"]), EXPECTED, out).status != PASS


def test_percentage_may_come_back_as_a_fraction():
    exp = ResultSet(columns=["p", "rate"], rows=[["A", 25.0], ["B", 50.0]])
    out = _out(["p", "rate"], [["A", 0.25], ["B", 0.5]])
    assert grade(_q(match=["p", "rate"]), exp, out).status == PASS


def test_ordered_mode_checks_order():
    exp = ResultSet(columns=["amount"], rows=[[30.0], [20.0], [10.0]])
    assert grade(_q("ordered", ["amount"]), exp, _out(["a"], [[30], [20], [10]])).status == PASS
    assert grade(_q("ordered", ["amount"]), exp, _out(["a"], [[10], [20], [30]])).status != PASS


def test_scalar_in_cell_or_message():
    exp = ResultSet(columns=["n"], rows=[[414]])
    assert grade(_q("scalar"), exp, _out(["count"], [[414]])).status == PASS
    assert grade(_q("scalar"), exp, _out(["count"], [[415]], "There are 414 customers")).status == PARTIAL
    assert grade(_q("scalar"), exp, _out(["count"], [[415]])).status == FAIL


def test_empty_mode():
    exp = ResultSet(columns=["loan"], rows=[])
    assert grade(_q("empty"), exp, _out(["loan"], [])).status == PASS
    assert grade(_q("empty"), exp, _out(["loan"], [["LN1"]])).status == FAIL


def test_pipeline_error_is_error():
    assert grade(_q(), EXPECTED, _out([], [], error="boom")).status == ERROR


def test_min_column_match():
    exp = ResultSet(columns=["a", "b"], rows=[[1, 2], [3, 4]])
    out = _out(["x", "y"], [[1, 9], [3, 9]])
    assert grade(_q(match=["a", "b"], min_column_match=1), exp, out).status == PASS


def test_allow_missing_zero_rows():
    exp = ResultSet(columns=["m", "loans"], rows=[["Jan", 3], ["Feb", 0], ["Mar", 2]])
    out = _out(["m", "n"], [["Jan", 3], ["Mar", 2]])
    assert grade(_q(match=["loans"], allow_missing_zero_rows=True), exp, out).status == PASS


def test_facts_mode():
    q = Question(id="T3", domain="d", category="two_source", sources=["DOC"], question="?",
                 compare={"mode": "facts"}, expected_facts=["1.29%", "not provided"])
    assert grade(q, None, _out([], [], "Highest slab is 1.29%; the policy was not provided.")).status == PASS
    assert grade(q, None, _out([], [], "Highest slab is 1.29%.")).status == PARTIAL
