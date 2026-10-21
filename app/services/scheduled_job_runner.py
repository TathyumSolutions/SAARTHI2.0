"""
Runs alerts and subscriptions.

Each run replays the job's saved query with no AI call, through the same
functions chat uses to replay a liked query (router_service.REUSE_DISPATCH:
_run_reused_db_query re-runs the stored SQL, _run_reused_spreadsheet_query
re-runs the stored plan), as the job's owner. DB replays skip the insight
LLM call too (with_insights=False). Alert rules are then checked in plain
Python (app/services/alert_rules.py).

run_due_jobs() is what the `flask run-due-jobs` command calls every minute
(see docs/ALERTS_AND_SUBSCRIPTIONS.md). It claims each due job by moving its
next_run_at forward with a conditional UPDATE before running it, so two
overlapping invocations never run the same job twice.
"""
import json
import re
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app import db
from app.models.scheduled_job import (
    ScheduledJob, ScheduledJobRun, JOB_TYPE_ALERT, STATUS_ACTIVE, STATUS_ERROR,
    RUN_OK, RUN_FIRED, RUN_SENT, RUN_SKIPPED, RUN_FAILED, TRIGGER_SCHEDULE, TRIGGER_TEST,
)
from app.models.user import User, STATUS_ACTIVE as USER_ACTIVE
from app.services.alert_rules import evaluate_rule
from app.services.email_service import send_email, smtp_configured
from app.services.job_notifications import build_email
from app.services.job_schedule import next_run_after

# Answers whose saved query can be replayed with no AI call - the same
# tracks chat's liked-query reuse supports.
SCHEDULABLE_TRACKS = ("DB", "SPREADSHEET")


def _json_safe(rows) -> List[Dict[str, Any]]:
    # Decimal/date/numpy values straight from the database, made plain so
    # they can be compared, stored on the run and put in an email.
    return json.loads(json.dumps([r for r in (rows or []) if isinstance(r, dict)], default=str))


def _clean_error(message: Optional[str]) -> str:
    text = re.sub(r"^[^\w]+", "", str(message or "")).strip()
    return text[:500] or "The saved query could not be run."


def replay_saved_query(job) -> Dict[str, Any]:
    """Re-runs the job's saved query as its owner. Returns {rows, answer,
    error} - error is a message, or None."""
    from app.services import router_service
    from app.services.stream_manager import stream_manager

    dispatch = router_service.REUSE_DISPATCH.get(job.router_decision)
    if job.router_decision not in SCHEDULABLE_TRACKS or not dispatch or not job.main_query:
        return {"rows": [], "answer": "", "error": "Only database and spreadsheet answers can be scheduled for now."}

    matched = SimpleNamespace(
        query_code=job.source_query_code or job.job_code or "saved query",
        main_query=job.main_query, answer=job.answer, sources=job.sources or [],
        question=job.question, remarks=None,
    )
    # A throwaway step-stream session: nobody listens to a scheduled run.
    session_id = f"scheduled-{job.job_code or 'draft'}-{uuid.uuid4().hex[:8]}"
    ctx = {
        "session_id": session_id, "model_name": None, "custom_key": "",
        "system_instructions": "", "user_id": job.user_id, "with_insights": False,
    }
    try:
        result = dispatch(job.question, matched, 1.0, ctx) or {}
    except Exception as e:
        print(f"⚠️ [ALERTS] Replay of {matched.query_code} failed: {e}")
        return {"rows": [], "answer": "", "error": _clean_error(str(e))}
    finally:
        stream_manager.clear(session_id)

    if result.get("error"):
        message = result.get("answer") or (
            "The saved query reads data you can no longer see, or it no longer runs."
        )
        return {"rows": [], "answer": "", "error": _clean_error(message)}
    return {"rows": _json_safe(result.get("table")), "answer": result.get("answer") or "", "error": None,
            "sources": result.get("sources")}


def _log_run_query(job, replay) -> Optional[str]:
    from app.services.router_service import _log_query
    return _log_query(
        job.user_id, job.company_code, job.question, job.router_decision, replay.get("answer"),
        f"Scheduled run of {job.job_code}: replayed the saved query"
        + (f" from {job.source_query_code}" if job.source_query_code else "")
        + " with no AI call.",
        replay.get("sources") or job.sources, job.main_query,
        execution_type="reused", matched_query_code=job.source_query_code,
        run_type=job.job_type, scheduled_job_id=job.id,
    )


def _owner_problem(owner) -> Optional[str]:
    if not owner:
        return "The owner's account no longer exists."
    if owner.status != USER_ACTIVE:
        return "The owner's account is not active."
    return None


def _send(job, recipients, rows, evaluation, run_time, is_test=False):
    email = build_email(job, rows, evaluation, run_time, is_test=is_test)
    attachments = [email["attachment"]] if email["attachment"] else []
    ok, error = send_email(recipients, email["subject"], email["text"], email["html"], attachments)
    return ok, error, email


def _mark_error(job, owner, error: str, now: datetime) -> None:
    """Marks the job as Error. Emails the owner once - when it goes into
    Error, not on every failed run, and never the recipients."""
    was_error = job.status == STATUS_ERROR
    job.status = STATUS_ERROR
    job.last_error = error
    if was_error or not owner or not owner.email:
        return
    kind = "alert" if job.job_type == JOB_TYPE_ALERT else "subscription"
    send_email(
        [owner.email],
        f"Saarthi: your {kind} \"{job.name}\" could not run",
        f"Your {kind} {job.job_code} \"{job.name}\" failed at {now:%d %b %Y %H:%M} UTC:\n\n{error}\n\n"
        "Nobody else was emailed. It keeps running on its schedule and goes back to normal on the "
        "next run that works. You can pause, edit or retry it under Reports > Alerts & Subscriptions.",
    )


def execute_job(job: ScheduledJob, trigger: str = TRIGGER_SCHEDULE, now: Optional[datetime] = None) -> ScheduledJobRun:
    """Runs one job now: replays its query, checks the rule (alerts),
    emails the recipients when it should, and records the run."""
    now = now or datetime.utcnow()
    owner = User.query.get(job.user_id)
    run = ScheduledJobRun(job_id=job.id, run_at=now, trigger=trigger)
    job.last_run_at = now

    problem = _owner_problem(owner)
    replay = {"rows": [], "error": problem} if problem else replay_saved_query(job)
    if replay["error"]:
        run.status, run.error = RUN_FAILED, replay["error"]
        _mark_error(job, owner, replay["error"], now)
        db.session.add(run)
        db.session.commit()
        return run

    rows = replay["rows"]
    run.query_code = _log_run_query(job, replay)
    run.row_count = len(rows)

    evaluation = None
    should_send = True
    if job.job_type == JOB_TYPE_ALERT:
        evaluation = evaluate_rule(job.rule or {}, rows, job.last_value)
        was_triggered = bool(job.is_triggered)
        job.last_value = evaluation["values"]
        job.is_triggered = evaluation["fired"]
        run.triggered_count = len(evaluation["triggered_rows"])
        run.value = evaluation["summary"]
        if not evaluation["fired"]:
            run.status, should_send = RUN_OK, False
        elif job.notify_once_until_recovered and was_triggered:
            run.status, should_send = RUN_FIRED, False
            run.value += " Not sent again until it recovers."
        elif job.min_gap_minutes and job.last_fired_at and now - job.last_fired_at < timedelta(minutes=job.min_gap_minutes):
            run.status, should_send = RUN_FIRED, False
            run.value += " Not sent: inside the minimum gap since the last alert."
    else:
        run.value = f"{len(rows)} row{'s' if len(rows) != 1 else ''}."
        if job.skip_if_empty and not rows:
            run.status, should_send = RUN_SKIPPED, False
            run.value = "No rows, so nothing was sent."

    if should_send:
        ok, error, _ = _send(job, job.recipients or [], rows, evaluation, now)
        if ok:
            run.status = RUN_SENT
            run.notified_to = list(job.recipients or [])
            job.last_fired_at = now
            if not smtp_configured():
                run.value = (run.value or "") + " (SMTP is not set up, so the email was written to the server log.)"
        else:
            run.status, run.error = RUN_FAILED, error
            _mark_error(job, owner, error, now)

    if run.status != RUN_FAILED and job.status == STATUS_ERROR:
        job.status = STATUS_ACTIVE
        job.last_error = None
    db.session.add(run)
    db.session.commit()
    return run


def preview_job(job) -> Dict[str, Any]:
    """The sample report: the email this job would send with today's data,
    built by running the query now. Sends nothing and records nothing."""
    now = datetime.utcnow()
    replay = replay_saved_query(job)
    if replay["error"]:
        return {"error": replay["error"]}
    rows = replay["rows"]
    evaluation = evaluate_rule(job.rule or {}, rows, job.last_value) if job.job_type == JOB_TYPE_ALERT else None
    email = build_email(job, rows, evaluation, now)
    would_send = True
    if evaluation is not None:
        would_send = evaluation["fired"]
    elif job.skip_if_empty and not rows:
        would_send = False
    return {
        "error": None,
        "subject": email["subject"],
        "html": email["html"],
        "text": email["text"],
        "to": list(job.recipients or []),
        "attachment_name": email["attachment_name"],
        "row_count": len(rows),
        "triggered_count": len(evaluation["triggered_rows"]) if evaluation else None,
        "summary": evaluation["summary"] if evaluation else f"{len(rows)} rows.",
        "would_send": would_send,
    }


def send_test(job, owner) -> Dict[str, Any]:
    """Sends the job's email to its creator only, with today's data, even
    when an alert's rule isn't met today. Changes nothing about the job;
    a saved job gets a 'test' run in its history."""
    now = datetime.utcnow()
    replay = replay_saved_query(job)
    if replay["error"]:
        return {"sent": False, "error": replay["error"]}
    rows = replay["rows"]
    evaluation = evaluate_rule(job.rule or {}, rows, job.last_value) if job.job_type == JOB_TYPE_ALERT else None
    ok, error, email = _send(job, [owner.email], rows, evaluation, now, is_test=True)
    if job.id:
        db.session.add(ScheduledJobRun(
            job_id=job.id, run_at=now, trigger=TRIGGER_TEST, status=RUN_SENT if ok else RUN_FAILED,
            row_count=len(rows), triggered_count=len(evaluation["triggered_rows"]) if evaluation else None,
            value="Test sent to the creator only." if ok else None, error=None if ok else error,
            notified_to=[owner.email] if ok else [],
        ))
        db.session.commit()
    return {"sent": ok, "error": error, "to": owner.email, "subject": email["subject"],
            "logged_only": ok and not smtp_configured()}


def run_due_jobs(now: Optional[datetime] = None, limit: int = 100) -> List[ScheduledJobRun]:
    """Runs every active (or erroring) job whose next run time has passed.
    Paused jobs are skipped. A job that missed several runs (the scheduler
    was down) runs once and moves on to its next future time."""
    now = now or datetime.utcnow()
    due = (
        ScheduledJob.query
        .filter(ScheduledJob.status.in_((STATUS_ACTIVE, STATUS_ERROR)))
        .filter(ScheduledJob.next_run_at.isnot(None))
        .filter(ScheduledJob.next_run_at <= now)
        .order_by(ScheduledJob.next_run_at)
        .limit(limit)
        .all()
    )
    runs = []
    for job in due:
        job_id, claimed_at = job.id, job.next_run_at
        try:
            following = next_run_after(job.schedule, now)
        except ValueError as e:
            following = None
            print(f"⚠️ [ALERTS] {job.job_code} has a bad schedule: {e}")
        claimed = (
            db.session.query(ScheduledJob)
            .filter(ScheduledJob.id == job_id, ScheduledJob.next_run_at == claimed_at)
            .update({ScheduledJob.next_run_at: following}, synchronize_session=False)
        )
        db.session.commit()
        if not claimed:
            continue  # another scheduler process got it first
        job = db.session.get(ScheduledJob, job_id)
        try:
            runs.append(execute_job(job, TRIGGER_SCHEDULE, now))
        except Exception as e:
            db.session.rollback()
            print(f"❌ [ALERTS] {job.job_code} failed unexpectedly: {e}")
    return runs
