"""
Guards for raw LLM text before it is trusted by the data-bridge pipeline.

Small local models (e.g. Llama 2 7B) routinely ignore "return ONLY ..."
instructions and wrap their answer in chatter ("Sure, here is ..."),
markdown fences, or a trailing "Explanation:" section. These helpers keep
only the part each pipeline step actually needs:

- sanitize_simplified_query: accept a simplifier rewrite only if it is a
  short plain-language question; otherwise fall back to the original.
- extract_sql: pull exactly one SQL statement out of a model reply,
  dropping any prose before or after it.
"""
import re
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Simplified-query guard
# ---------------------------------------------------------------------------

_SQL_SHAPE_RE = re.compile(
    r"```|\bSELECT\b[\s\S]+?\bFROM\b|\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b"
    r"|\bDELETE\s+FROM\b|\bCREATE\s+TABLE\b|\bGROUP\s+BY\b",
    re.IGNORECASE,
)
_CHATTER_RE = re.compile(
    r"^\s*(?:sure|certainly|of course|absolutely|okay|ok\b|great|here(?:'s| is| are)"
    r"|i can|i'd|i would|i will|i'll|to (?:get|answer|find))"
    r"|simplified query|simplified version",
    re.IGNORECASE,
)
_MAX_LINES = 3
_MAX_EXTRA_CHARS = 150


def _strip_wrapping_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'`":
        return text[1:-1].strip()
    return text


def sanitize_simplified_query(candidate: Optional[str], original: str) -> Tuple[str, Optional[str]]:
    """Return (query_to_use, rejection_reason).

    rejection_reason is None when the candidate was accepted. Falling back to
    the original question is always safe - it is what the user typed.
    """
    raw = (candidate or "").strip()
    text = _strip_wrapping_quotes(raw)
    if not text:
        return original, "empty output"
    if _SQL_SHAPE_RE.search(raw):
        return original, "output contains SQL or code"
    if _CHATTER_RE.search(text):
        return original, "output contains conversational filler"
    if len([ln for ln in text.splitlines() if ln.strip()]) > _MAX_LINES:
        return original, "output spans too many lines"
    if len(text) > max(2 * len(original), len(original) + _MAX_EXTRA_CHARS):
        return original, "output is much longer than the question"
    return text, None


# ---------------------------------------------------------------------------
# SQL extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z]*)[ \t]*\n?(.*?)```", re.DOTALL)
_STATEMENT_START_RE = re.compile(
    r"\b(?:SELECT\b|WITH\s+(?:RECURSIVE\s+)?[A-Za-z_][\w]*\s*(?:\([^)]*\)\s*)?AS\s*\()",
    re.IGNORECASE,
)
_HAS_FROM_RE = re.compile(r"\bFROM\b", re.IGNORECASE)
# A line that starts a prose section after the statement.
_PROSE_LINE_RE = re.compile(
    r"^\s*(?:[*•#>]|-(?!-)|\d+[.)]\s|(?:note|explanation|explained|this query|the query"
    r"|here|i have|i've|output|result|where:|assumptions?)\b)",
    re.IGNORECASE,
)
# Keywords that may legitimately start a line continuing a statement after a
# blank line.
_SQL_CONTINUATION_RE = re.compile(
    r"^\s*(?:select|from|where|join|inner|left|right|full|cross|on|and|or|group|order"
    r"|having|limit|offset|union|intersect|except|with|as|case|when|then|else|end|[(),])",
    re.IGNORECASE,
)


def _scan_statement(text: str) -> str:
    """Read one statement from the start of `text`.

    Stops at the first `;` outside quotes/comments (kept), at a closing code
    fence, or at a prose section. Drops `--` comments and MySQL-style
    backticks, which PostgreSQL rejects.
    """
    out = []
    i, n = 0, len(text)
    in_single = in_double = False
    at_line_start = False
    while i < n:
        ch = text[i]
        if in_single:
            out.append(ch)
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue

        if at_line_start:
            line_end = text.find("\n", i)
            line = text[i:] if line_end == -1 else text[i:line_end]
            if not line.strip():
                # Blank line: continue only if the next non-blank line still
                # looks like SQL.
                rest = text[i:].lstrip()
                if not rest or not _SQL_CONTINUATION_RE.match(rest):
                    break
            elif _PROSE_LINE_RE.match(line) or line.lstrip().startswith("```"):
                break
            at_line_start = False

        if ch == "'":
            in_single = True
            out.append(ch)
        elif ch == '"':
            in_double = True
            out.append(ch)
        elif ch == "-" and text.startswith("--", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        elif ch == "`":
            if text.startswith("```", i):
                break
        elif ch == ";":
            out.append(ch)
            break
        elif ch == "\n":
            out.append(ch)
            at_line_start = True
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _normalize(statement: str) -> str:
    lines = [ln.strip() for ln in statement.splitlines() if ln.strip()]
    return " ".join(lines).strip()


def _starts_line(text: str, pos: int) -> bool:
    """True if only whitespace or an opening quote precedes `pos` on its line."""
    line_start = text.rfind("\n", 0, pos) + 1
    return not text[line_start:pos].strip(" \t\"'\u201c")


def _statements_in(text: str) -> list:
    """All candidate statements, ordered best first: a statement that starts
    its own line and has a FROM clause beats one embedded mid-sentence
    ("I will SELECT the right columns...")."""
    statements = []
    for m in _STATEMENT_START_RE.finditer(text):
        segment = text[m.start():]
        # A statement quoted in prose - "SELECT ... FROM t" - ends at the
        # matching closing quote, which would otherwise be read as the
        # start of a quoted identifier and swallow everything after it.
        opener = text[m.start() - 1] if m.start() > 0 else ""
        if opener in ("\"", "“"):
            closer = "”" if opener == "“" else "\""
            end = segment.find(closer)
            if end != -1:
                segment = segment[:end]
        stmt = _normalize(_scan_statement(segment))
        if stmt:
            rank = (0 if _starts_line(text, m.start()) else 1) + (0 if _HAS_FROM_RE.search(stmt) else 2)
            statements.append((rank, len(statements), stmt))
    return [stmt for _, _, stmt in sorted(statements)]


def extract_sql(raw: Optional[str]) -> str:
    """Return the single SQL statement in a model reply, or "" if none.

    Prefers a fenced ```sql block; otherwise takes the first SELECT/WITH
    statement that starts its own line and has a FROM clause (falling back
    to the next best candidate), cutting off any explanation after it.
    """
    if not raw or not raw.strip():
        return ""

    for _lang, body in _FENCE_RE.findall(raw):
        candidates = _statements_in(body)
        if candidates:
            return candidates[0]

    candidates = _statements_in(raw)
    return candidates[0] if candidates else ""
