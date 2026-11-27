"""Checks the question banks themselves: every placeholder resolves, every
reference query runs against the loaded demo data and still returns the
saved snapshot. Skipped when the demo databases are not reachable."""
import psycopg2
import pytest

from regression.bank import available_domains, load_bank
from regression.stage_checks import check_reference
from regression.evaluator import PASS, SKIP
from regression.settings import demo_db_target


def _reachable(dbname):
    try:
        psycopg2.connect(**demo_db_target(dbname).as_psycopg2(), connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.mark.parametrize("domain", available_domains())
def test_bank_loads_and_ids_are_unique(domain):
    bank = load_bank(domain)
    ids = [q.id for q in bank.questions]
    assert len(ids) == len(set(ids))
    for q in bank.questions:
        assert q.compare.get("mode"), q.id
        assert q.has_reference or q.compare["mode"] == "facts", q.id


def _cases():
    for domain in available_domains():
        bank = load_bank(domain)
        for q in bank.questions:
            if q.has_reference:
                yield pytest.param(domain, q.id, id=f"{domain}-{q.id}")


@pytest.mark.parametrize("domain,qid", list(_cases()))
def test_reference_sql_matches_snapshot(domain, qid):
    bank = load_bank(domain)
    if not _reachable(bank.database):
        pytest.skip(f"{bank.database} not reachable")
    result = check_reference(bank, bank.get(qid), demo_db_target(bank.database))
    assert result.status in (PASS, SKIP), result.detail


@pytest.mark.parametrize("domain,qid", list(_cases()))
def test_reference_answer_grades_as_pass(domain, qid):
    """The compare spec accepts the reference result itself, with the
    columns renamed and the rows shuffled (unless order matters)."""
    from regression.evaluator import grade
    from regression.pipeline_runner import PipelineOutcome
    from regression.reference import load_snapshot

    bank = load_bank(domain)
    question = bank.get(qid)
    expected = load_snapshot(domain, qid)
    if expected is None:
        pytest.skip("no snapshot")
    rows = [list(r) for r in expected.rows]
    if question.compare.get("mode") != "ordered":
        rows = rows[::-1]
    outcome = PipelineOutcome(question_id=qid, columns=[f"col_{i}" for i in range(len(expected.columns))], rows=rows)
    verdict = grade(question, expected, outcome)
    assert verdict.status == PASS, verdict.detail
