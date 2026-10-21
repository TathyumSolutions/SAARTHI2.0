"""
Alert/subscription code generation - every ScheduledJob gets a fixed-width
code, ALRT##### for alerts and SUBS##### for subscriptions (4 letters + 5
zero-padded digits, e.g. ALRT00001), mirroring app/utils/query_codes.py's
QUERY##### scheme. Each type has its own sequence.
"""
from app.models.scheduled_job import ScheduledJob, JOB_TYPE_ALERT

CODE_PREFIXES = {JOB_TYPE_ALERT: "ALRT", "S": "SUBS"}
CODE_DIGITS = 5


def _next_sequence_number(prefix: str) -> int:
    last = (
        ScheduledJob.query
        .filter(ScheduledJob.job_code.like(f"{prefix}%"))
        .order_by(ScheduledJob.id.desc())
        .first()
    )
    if not last or not last.job_code:
        return 1
    try:
        return int(last.job_code[len(prefix):]) + 1
    except ValueError:
        return ScheduledJob.query.filter(ScheduledJob.job_code.like(f"{prefix}%")).count() + 1


def generate_job_code(job_type: str) -> str:
    """Returns the next code for this job type, e.g. "ALRT00001". Retries a
    handful of times past a code another request just took."""
    prefix = CODE_PREFIXES[job_type]
    number = _next_sequence_number(prefix)
    for _ in range(5):
        candidate = f"{prefix}{number:0{CODE_DIGITS}d}"
        if not ScheduledJob.query.filter_by(job_code=candidate).first():
            return candidate
        number += 1
    return f"{prefix}{number:0{CODE_DIGITS}d}"
