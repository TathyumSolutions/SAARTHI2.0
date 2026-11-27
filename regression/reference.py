"""Runs a question's reference SQL - the hand-checked ground truth - and
stores the result as an expected snapshot."""
import datetime
import decimal
import json
from dataclasses import dataclass, field
from pathlib import Path

import psycopg2

from regression.bank import Question
from regression.settings import DbTarget

EXPECTED_DIR = Path(__file__).resolve().parent / "expected"
STATEMENT_TIMEOUT_MS = 120_000


@dataclass
class ResultSet:
    columns: list
    rows: list  # list of lists, JSON-safe values
    parts: dict = field(default_factory=dict)  # extra part name -> ResultSet

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_json(self) -> dict:
        return {"columns": self.columns, "rows": self.rows,
                "parts": {k: v.to_json() for k, v in self.parts.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "ResultSet":
        return cls(columns=data["columns"], rows=data["rows"],
                   parts={k: cls.from_json(v) for k, v in (data.get("parts") or {}).items()})


def json_safe(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return value.days
    return value


def run_sql(target: DbTarget, sql: str) -> ResultSet:
    conn = psycopg2.connect(**target.as_psycopg2(), connect_timeout=10)
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            cur.execute(sql)
            columns = [d[0] for d in cur.description]
            rows = [[json_safe(v) for v in r] for r in cur.fetchall()]
        return ResultSet(columns=columns, rows=rows)
    finally:
        conn.close()


def run_reference(question: Question, target: DbTarget) -> ResultSet:
    result = run_sql(target, question.reference_sql)
    for part in question.extra_parts:
        result.parts[part["name"]] = run_sql(target, part["sql"])
    return result


def snapshot_path(domain: str, question_id: str) -> Path:
    return EXPECTED_DIR / domain / f"{question_id}.json"


def save_snapshot(domain: str, question_id: str, result: ResultSet, meta: dict) -> Path:
    path = snapshot_path(domain, question_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_snapshot_text(meta, result), encoding="utf-8")
    return path


def _rows_text(rows: list, indent: str) -> str:
    """One row per line, so a changed value shows as a one-line diff."""
    if not rows:
        return "[]"
    body = (",\n" + indent + "  ").join(json.dumps(r, default=str, ensure_ascii=False) for r in rows)
    return "[\n" + indent + "  " + body + "\n" + indent + "]"


def _result_text(result: ResultSet, indent: str) -> str:
    parts = ""
    if result.parts:
        inner = (",\n" + indent + "  ").join(
            f"{json.dumps(name)}: {_result_text(part, indent + '  ')}" for name, part in result.parts.items())
        parts = ",\n" + indent + ' "parts": {\n' + indent + "  " + inner + "\n" + indent + " }"
    return ("{\n" + indent + ' "columns": ' + json.dumps(result.columns) + ",\n"
            + indent + ' "rows": ' + _rows_text(result.rows, indent + " ") + parts + "\n" + indent + "}")


def _snapshot_text(meta: dict, result: ResultSet) -> str:
    return ('{\n "meta": ' + json.dumps(meta, default=str, ensure_ascii=False) + ',\n "result": '
            + _result_text(result, " ") + "\n}\n")


def load_snapshot(domain: str, question_id: str):
    path = snapshot_path(domain, question_id)
    if not path.exists():
        return None
    return ResultSet.from_json(json.loads(path.read_text(encoding="utf-8"))["result"])
