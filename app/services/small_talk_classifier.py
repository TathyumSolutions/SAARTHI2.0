"""
Zero-cost "is this just small talk?" check, run before the LLM router.

A match sends the message straight to the GENERAL track and skips every
connected data source, so a false positive silently throws away a real
data question. It must therefore be conservative:

* Phrases match whole words only - "hey" must not fire inside "they",
  "hi" not inside "Delhi" (the old plain-substring check did both).
* Only short messages qualify (``max_words``).
* Any data term or digit in the message vetoes the shortcut.
* A phrase only counts when it is nearly the whole message: at most
  ``max_extra_words`` other words around it, separately for greetings
  and for date/time questions ("what month is it" yes,
  "what month had the highest NPA" no).

Everything tunable lives in general_knowledge_config.json so the lists
can be edited without touching code. When in doubt this returns None and
the LLM router decides, which only costs a router call.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

_DEFAULT_MAX_WORDS = 8
_DEFAULT_MAX_EXTRA_WORDS = {"greeting_patterns": 3, "time_and_date_patterns": 2}

_APOSTROPHES = re.compile(r"[’'`]")
_NON_WORD = re.compile(r"[^\w\s]")
_DIGIT = re.compile(r"\d")


def _normalize(text: str) -> str:
    """Lower-case, drop apostrophes (today's -> todays), turn other
    punctuation into spaces and collapse whitespace."""
    text = _APOSTROPHES.sub("", text.lower())
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split())


def _phrase_regex(phrase: str) -> Optional[re.Pattern]:
    norm = _normalize(phrase)
    if not norm:
        return None
    return re.compile(rf"(?<!\w){re.escape(norm)}(?!\w)")


def _strings(values: Iterable) -> list[str]:
    return [v for v in values if isinstance(v, str) and v.strip()]


def _contains_data_term(words: set[str], normalized: str, data_terms: list[str]) -> bool:
    for term in data_terms:
        norm = _normalize(term)
        if not norm:
            continue
        if " " in norm:
            if re.search(rf"(?<!\w){re.escape(norm)}(?!\w)", normalized):
                return True
        elif norm in words:
            return True
    return False


def classify_small_talk(user_query: str, routing_cfg: dict) -> Optional[str]:
    """Return "GENERAL" when ``user_query`` is clearly a greeting or a bare
    date/time question, else None (let the LLM router decide).

    ``routing_cfg`` is the ``general_knowledge_routing`` section of
    general_knowledge_config.json.
    """
    if not user_query or not isinstance(routing_cfg, dict):
        return None

    normalized = _normalize(user_query)
    if not normalized:
        return None
    words = normalized.split()

    guards = routing_cfg.get("guards", {}) or {}
    max_words = int(guards.get("max_words", _DEFAULT_MAX_WORDS))
    if len(words) > max_words:
        return None
    if guards.get("block_if_contains_digit", True) and _DIGIT.search(normalized):
        return None
    if _contains_data_term(set(words), normalized, _strings(guards.get("data_terms", []))):
        return None

    extra_limits = {**_DEFAULT_MAX_EXTRA_WORDS, **(guards.get("max_extra_words", {}) or {})}
    indicators = routing_cfg.get("strong_general_indicators", {}) or {}

    for group, patterns in indicators.items():
        if not isinstance(patterns, list):
            continue
        allowed_extra = int(extra_limits.get(group, 0))
        for phrase in _strings(patterns):
            rx = _phrase_regex(phrase)
            if rx is None:
                continue
            match = rx.search(normalized)
            if not match:
                continue
            leftover = (normalized[: match.start()] + " " + normalized[match.end():]).split()
            if len(leftover) <= allowed_extra:
                return "GENERAL"
    return None
