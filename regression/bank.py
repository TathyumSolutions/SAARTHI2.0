"""Loads a question bank YAML file and renders its {{placeholders}}."""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

BANK_DIR = Path(__file__).resolve().parent / "question_bank"
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@dataclass
class Question:
    id: str
    domain: str
    category: str
    sources: list
    question: str
    expected_logic: str = ""
    reference_sql: Optional[str] = None
    extra_parts: list = field(default_factory=list)
    compare: dict = field(default_factory=dict)
    expected_facts: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    @property
    def is_db_only(self) -> bool:
        return self.sources == ["DB"]

    @property
    def has_reference(self) -> bool:
        return bool(self.reference_sql)


@dataclass
class Bank:
    domain: str
    database: str
    params: dict
    questions: list
    refusal_tests: list
    data_scale: str = ""

    def get(self, question_id: str) -> Question:
        for q in self.questions:
            if q.id == question_id:
                return q
        raise KeyError(question_id)


def render(text: Optional[str], values: dict) -> Optional[str]:
    """Replaces {{name}}; snippets may hold placeholders themselves."""
    if text is None:
        return None
    for _ in range(3):
        rendered = _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)
        if rendered == text:
            break
        text = rendered
    missing = _PLACEHOLDER.findall(text)
    if missing:
        raise KeyError(f"Unresolved placeholders: {sorted(set(missing))}")
    return text


_KNOWN_KEYS = {"id", "category", "sources", "question", "expected_logic", "reference_sql",
               "extra_parts", "compare", "expected_facts"}


def load_bank(domain: str) -> Bank:
    raw = yaml.safe_load((BANK_DIR / f"{domain}.yaml").read_text(encoding="utf-8"))
    values = {**(raw.get("params") or {}), **(raw.get("snippets") or {})}
    questions = []
    for q in raw.get("questions") or []:
        questions.append(Question(
            id=q["id"],
            domain=raw["domain"],
            category=q["category"],
            sources=list(q.get("sources") or []),
            question=render(q["question"], values),
            expected_logic=render(q.get("expected_logic", ""), values),
            reference_sql=render(q.get("reference_sql"), values),
            extra_parts=[{"name": p["name"], "sql": render(p["sql"], values)} for p in q.get("extra_parts") or []],
            compare=q.get("compare") or {},
            expected_facts=list(q.get("expected_facts") or []),
            notes={k: v for k, v in q.items() if k not in _KNOWN_KEYS},
        ))
    return Bank(domain=raw["domain"], database=raw["database"], params=raw.get("params") or {},
                questions=questions, refusal_tests=list(raw.get("refusal_tests") or []),
                data_scale=str(raw.get("data_scale") or ""))


def available_domains() -> list:
    return sorted(p.stem for p in BANK_DIR.glob("*.yaml"))
