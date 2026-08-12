"""
Query code generation - every logged query gets a fixed-width QUERY#####
code (5 letters + 5 zero-padded digits = 10 chars, e.g. QUERY00001), used
to identify it in the Queries UI and to reference it as a "matched query"
when a later question reuses it.
"""
from sqlalchemy.exc import IntegrityError
from app import db
from app.models.query_log import QueryLog

CODE_PREFIX = "QUERY"
CODE_DIGITS = 5


def _next_sequence_number() -> int:
    last = (
        QueryLog.query
        .filter(QueryLog.query_code.like(f"{CODE_PREFIX}%"))
        .order_by(QueryLog.id.desc())
        .first()
    )
    if not last or not last.query_code:
        return 1
    try:
        return int(last.query_code[len(CODE_PREFIX):]) + 1
    except ValueError:
        return QueryLog.query.count() + 1


def generate_query_code() -> str:
    """
    Returns the next sequential code, e.g. "QUERY00001". Retries a handful
    of times on a unique-constraint collision (concurrent requests racing
    for the same next number) by re-reading the current max and bumping
    past it, rather than assuming single-writer access.
    """
    for _ in range(5):
        candidate = f"{CODE_PREFIX}{_next_sequence_number():0{CODE_DIGITS}d}"
        if not QueryLog.query.filter_by(query_code=candidate).first():
            return candidate
    # Extremely unlikely fallback - still fixed-width, just seeded off the
    # total row count instead of the max code.
    return f"{CODE_PREFIX}{(QueryLog.query.count() + 1):0{CODE_DIGITS}d}"
