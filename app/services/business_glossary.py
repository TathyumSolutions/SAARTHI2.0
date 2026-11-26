"""
Business glossary: which source a business term's figures come from.

Without it the system guesses a term from the nearest-sounding column -
"cost to acquire the loan" was answered with processing_fee_pct (income)
instead of the agent commission in the uploaded slab sheet. Terms and
aliases live in business_glossary.json; only the terms a question actually
uses are added to the router / database-planner prompts, so unrelated
questions pay no extra tokens.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import List

_GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "business_glossary.json")

_APOSTROPHES = re.compile(r"[’'`]")


def _normalize(text: str) -> str:
    text = _APOSTROPHES.sub("", str(text or "").lower())
    return " ".join(re.sub(r"[^\w.%]+", " ", text).split())


@lru_cache(maxsize=1)
def _load_terms(path: str = _GLOSSARY_PATH) -> tuple:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"⚠️ [GLOSSARY] Could not load {path}: {e}")
        return tuple()
    terms = []
    for entry in data.get("terms", []):
        if not isinstance(entry, dict) or not entry.get("term"):
            continue
        phrases = {_normalize(entry["term"])} | {_normalize(a) for a in entry.get("aliases", []) if isinstance(a, str)}
        patterns = tuple(re.compile(rf"(?<!\w){re.escape(p)}(?!\w)") for p in phrases if p)
        terms.append((entry, patterns))
    return tuple(terms)


def matching_terms(user_query: str) -> List[dict]:
    """Glossary entries whose term or an alias appears (whole words) in the question."""
    q = _normalize(user_query)
    if not q:
        return []
    return [entry for entry, patterns in _load_terms() if any(p.search(q) for p in patterns)]


def glossary_block(user_query: str) -> str:
    """Prompt section defining the business terms used in ``user_query``,
    or "" when none are used."""
    entries = matching_terms(user_query)
    if not entries:
        return ""
    lines = [
        "BUSINESS TERMS USED IN THIS QUESTION (company definitions - follow them; "
        "do not substitute a similar-sounding column):"
    ]
    for e in entries:
        line = f"- {e['term']}: {e.get('meaning', '').strip()}"
        if e.get("source"):
            line += f" Source: {e['source'].strip()}"
        if e.get("not"):
            line += f" {e['not'].strip()}"
        lines.append(line)
    return "\n".join(lines)


def reload_glossary() -> None:
    """Drop the cached glossary (after editing business_glossary.json)."""
    _load_terms.cache_clear()
