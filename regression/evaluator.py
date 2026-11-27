"""Grades a pipeline result against the reference result.

The pipeline names its own columns, so matching is by value: each
reference column listed in `compare.match_columns` must have a pipeline
column holding the same values (as a multiset, or in order for
`mode: ordered`). Numbers match within a relative tolerance, and a
percentage may come back as a fraction or vice versa (x100 / /100).

Compare modes (question bank `compare.mode`):
  scalar   one value; any cell of a one-row answer, or a number in the message
  set      row count and matched columns, order ignored
  ordered  like set, but values must appear in reference order
  empty    the correct answer has no rows
  facts    no SQL ground truth; phrases from `expected_facts` in the answer
"""
import datetime
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from regression.bank import Question
from regression.reference import ResultSet

PASS, PARTIAL, FAIL, ERROR, SKIP = "PASS", "PARTIAL", "FAIL", "ERROR", "SKIP"
DEFAULT_REL_TOL = 0.0005
ABS_TOL = 0.011
_NUMBER_IN_TEXT = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


@dataclass
class Verdict:
    status: str
    detail: str = ""
    matched_columns: dict = field(default_factory=dict)  # reference col -> pipeline col
    missing_columns: list = field(default_factory=list)
    expected_rows: Optional[int] = None
    actual_rows: Optional[int] = None
    facts_found: list = field(default_factory=list)
    facts_missing: list = field(default_factory=list)

    def to_json(self) -> dict:
        return dict(self.__dict__)


# ------------------------------------------------------------ normalising

def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").rstrip("%")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()[:10]
    text = str(value).strip()
    # "2026-04-01T00:00:00" / "2026-04-01 00:00:00" -> "2026-04-01"
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]00:00:00", text):
        text = text[:10]
    return text.casefold()


def _numbers_close(a: float, b: float, rel_tol: float) -> bool:
    """Whole numbers (counts, rupee totals) must match exactly; the
    tolerance absorbs rounding of averages, rates and shares only."""
    if float(a).is_integer() and float(b).is_integer():
        return a == b
    return abs(a - b) <= max(ABS_TOL, rel_tol * abs(b))


def _column(rows: list, index: int) -> list:
    return [r[index] if index < len(r) else None for r in rows]


def _numeric_column(values: list):
    nums = [_as_number(v) for v in values]
    non_null = [v for v in values if v is not None]
    if non_null and all(_as_number(v) is not None for v in non_null):
        return [n if n is not None else 0.0 for n in nums]
    return None


def _values_match(expected: list, actual: list, ordered: bool, rel_tol: float) -> bool:
    if len(expected) != len(actual):
        return False
    exp_num, act_num = _numeric_column(expected), _numeric_column(actual)
    if exp_num is not None and act_num is not None:
        for scale in (1.0, 100.0, 0.01):
            scaled = [a * scale for a in act_num]
            e, a = (exp_num, scaled) if ordered else (sorted(exp_num), sorted(scaled))
            if all(_numbers_close(x, y, rel_tol) for x, y in zip(a, e)):
                return True
        return False
    exp_txt, act_txt = [_as_text(v) for v in expected], [_as_text(v) for v in actual]
    return exp_txt == act_txt if ordered else Counter(exp_txt) == Counter(act_txt)


# ------------------------------------------------------------ grading

def _grade_facts(question: Question, message: str) -> Verdict:
    text = (message or "").casefold()
    found = [f for f in question.expected_facts if f.casefold() in text]
    missing = [f for f in question.expected_facts if f.casefold() not in text]
    status = PASS if not missing else (PARTIAL if found else FAIL)
    return Verdict(status=status, detail=f"{len(found)}/{len(question.expected_facts)} expected facts in the answer",
                   facts_found=found, facts_missing=missing)


def _grade_scalar(expected: ResultSet, columns: list, rows: list, message: str, rel_tol: float) -> Verdict:
    if not expected.rows or not expected.rows[0]:
        return Verdict(status=ERROR, detail="reference returned no value")
    target = expected.rows[0][0]
    target_num = _as_number(target)
    candidates = list(rows[0]) if len(rows) == 1 else []
    if len(rows) > 1 and columns and len(columns) == 1:
        candidates = [r[0] for r in rows]
    for value in candidates:
        num = _as_number(value)
        if target_num is not None and num is not None and _numbers_close(num, target_num, rel_tol):
            return Verdict(status=PASS, detail=f"value {value} matches {target}", expected_rows=1, actual_rows=len(rows))
        if target_num is None and _as_text(value) == _as_text(target):
            return Verdict(status=PASS, detail=f"value {value!r} matches", expected_rows=1, actual_rows=len(rows))
    if target_num is not None:
        for token in _NUMBER_IN_TEXT.findall(message or ""):
            num = _as_number(token)
            if num is not None and _numbers_close(num, target_num, rel_tol):
                return Verdict(status=PARTIAL, detail=f"{target} appears in the answer text, not as a result cell",
                               expected_rows=1, actual_rows=len(rows))
    return Verdict(status=FAIL, detail=f"expected {target}; got {rows[:3]}", expected_rows=1, actual_rows=len(rows))


def _grade_table(question: Question, expected: ResultSet, columns: list, rows: list, rel_tol: float) -> Verdict:
    spec = question.compare
    ordered = spec.get("mode") == "ordered"
    exp_rows = expected.rows
    if spec.get("allow_missing_zero_rows") and len(rows) < len(exp_rows):
        keep_idx = [expected.columns.index(c) for c in spec.get("match_columns", []) if c in expected.columns]
        exp_rows = [r for r in exp_rows if any((_as_number(r[i]) or 0) != 0 for i in keep_idx)]
    expected_view = ResultSet(columns=expected.columns, rows=exp_rows)

    verdict = Verdict(status=FAIL, expected_rows=len(exp_rows), actual_rows=len(rows))
    if len(rows) != len(exp_rows):
        verdict.detail = f"row count {len(rows)}, expected {len(exp_rows)}"

    wanted = [c for c in spec.get("match_columns") or expected.columns if c in expected.columns]
    used = set()
    for col in wanted:
        exp_values = _column(expected_view.rows, expected.columns.index(col))
        for j in range(len(columns)):
            if j in used:
                continue
            if _values_match(exp_values, _column(rows, j), ordered, rel_tol):
                verdict.matched_columns[col] = columns[j]
                used.add(j)
                break
        else:
            verdict.missing_columns.append(col)

    needed = spec.get("min_column_match", len(wanted))
    if len(rows) == len(exp_rows) and len(verdict.matched_columns) >= needed:
        verdict.status = PASS
        verdict.detail = f"{len(rows)} rows; matched {verdict.matched_columns}"
    elif verdict.matched_columns or (len(rows) == len(exp_rows) and rows):
        verdict.status = PARTIAL
        verdict.detail = (verdict.detail + "; " if verdict.detail else "") + \
            f"matched {sorted(verdict.matched_columns)}, missing {verdict.missing_columns}"
    else:
        verdict.detail = (verdict.detail + "; " if verdict.detail else "") + f"no column matched {wanted}"
    return verdict


def grade(question: Question, expected: Optional[ResultSet], outcome) -> Verdict:
    """outcome: a pipeline_runner.PipelineOutcome."""
    mode = question.compare.get("mode", "set")
    rel_tol = float(question.compare.get("tolerance", DEFAULT_REL_TOL))
    if mode == "facts" or expected is None:
        if not question.expected_facts:
            return Verdict(status=SKIP, detail="no reference SQL and no expected facts")
        return _grade_facts(question, outcome.message)
    if outcome.error:
        return Verdict(status=ERROR, detail=str(outcome.error).splitlines()[0][:300])
    if mode == "empty":
        if not outcome.rows:
            return Verdict(status=PASS, detail="correctly returned no rows", expected_rows=0, actual_rows=0)
        return Verdict(status=FAIL, detail=f"expected no rows; got {len(outcome.rows)}",
                       expected_rows=0, actual_rows=len(outcome.rows))
    if mode == "scalar":
        return _grade_scalar(expected, outcome.columns, outcome.rows, outcome.message, rel_tol)
    return _grade_table(question, expected, outcome.columns, outcome.rows, rel_tol)
