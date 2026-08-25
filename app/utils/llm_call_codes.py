"""
LLM call code generation - every logged LLM call gets a fixed-width
LLMC######## code (4 letters + 8 zero-padded digits = 12 chars, e.g.
LLMC00000001), mirroring app/utils/query_codes.py's QUERY##### scheme.
"""
from app.models.llm_call_log import LLMCallLog

CODE_PREFIX = "LLMC"
CODE_DIGITS = 8


def _next_sequence_number() -> int:
    last = (
        LLMCallLog.query
        .filter(LLMCallLog.call_code.like(f"{CODE_PREFIX}%"))
        .order_by(LLMCallLog.id.desc())
        .first()
    )
    if not last or not last.call_code:
        return 1
    try:
        return int(last.call_code[len(CODE_PREFIX):]) + 1
    except ValueError:
        return LLMCallLog.query.count() + 1


def generate_call_code() -> str:
    """
    Returns the next sequential code, e.g. "LLMC00000001". Retries a
    handful of times on a unique-constraint collision (concurrent requests
    racing for the same next number) by re-reading the current max and
    bumping past it, rather than assuming single-writer access.
    """
    for _ in range(5):
        candidate = f"{CODE_PREFIX}{_next_sequence_number():0{CODE_DIGITS}d}"
        if not LLMCallLog.query.filter_by(call_code=candidate).first():
            return candidate
    return f"{CODE_PREFIX}{(LLMCallLog.query.count() + 1):0{CODE_DIGITS}d}"
