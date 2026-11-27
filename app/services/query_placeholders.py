"""
Resolve `:name` placeholders left in a user's question before any LLM sees it.

Questions are often copied from a report template or a saved query and still
carry bind-parameter placeholders such as ":as_of" or ":plant". Passed through
as-is, every downstream model invents its own value for them (e.g. Llama 2
turned "12 months to :as_of" into `YEAR(PO_DATE) IN (LAST_12_MONTHS)`).

- Date-like placeholders (:as_of, :today, :start_date, :period_end, ...) are
  replaced with today's date - the only sensible default.
- Any other placeholder (:plant, :supplier, ...) has no safe default, so it is
  reported back as unresolved and the caller should ask the user for it.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# ":name" preceded by start-of-text or a non-word, non-colon character, so
# times ("10:30"), Postgres casts ("x::date"), URLs ("http://") and labels
# written without a space ("Note:abc") are never treated as placeholders.
_PLACEHOLDER_RE = re.compile(r"(?<![\w:]):([A-Za-z_][A-Za-z0-9_]*)\b")

_DATE_NAME_RE = re.compile(
    r"^(?:as_?of(?:_date)?|today|now|current_date|cutoff(?:_date)?|report_date"
    r"|(?:\w+_)?date(?:_\w+)?"
    r"|(?:start|end|from|to|period_start|period_end)(?:_date)?)$",
    re.IGNORECASE,
)


@dataclass
class PlaceholderResolution:
    text: str
    resolved: dict = field(default_factory=dict)
    unresolved: list = field(default_factory=list)


def is_date_placeholder(name: str) -> bool:
    return bool(_DATE_NAME_RE.match(name))


def resolve_query_placeholders(text: str, today: Optional[date] = None) -> PlaceholderResolution:
    """Replace date-like `:name` placeholders with today's ISO date and list
    the rest as unresolved (in first-seen order, without duplicates)."""
    if not text:
        return PlaceholderResolution(text=text or "")

    today_iso = (today or date.today()).isoformat()
    resolved: dict = {}
    unresolved: list = []

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if is_date_placeholder(name):
            resolved[name] = today_iso
            return today_iso
        if name not in unresolved:
            unresolved.append(name)
        return match.group(0)

    new_text = _PLACEHOLDER_RE.sub(_replace, text)
    return PlaceholderResolution(text=new_text, resolved=resolved, unresolved=unresolved)


def build_missing_value_question(unresolved: list) -> str:
    """User-facing prompt asking for the values we could not fill in."""
    names = ", ".join(f":{n}" for n in unresolved)
    noun = "a placeholder" if len(unresolved) == 1 else "placeholders"
    return (
        f"Your question contains {noun} I can't fill in on my own: {names}. "
        "Please ask again with the actual value(s) in place of the placeholder."
    )
