"""
Alerts & Subscriptions API

Backs two pages: Management > Alerts & Subscriptions (the create screen,
/alerts/new) and Reports > Alerts & Subscriptions (the list with run
history, /alerts).

Who sees what: every user manages their own jobs; a company admin can see
and manage every job in their company. A job always runs as its owner,
whoever edits it.

Data for a job comes from one of the owner's own Query Logs entries - an
existing one, or one created on the spot by asking a new question through
the normal answer pipeline with run_type A or S. Only database and
spreadsheet answers can be scheduled for now, since those are the ones a
scheduled run can replay with no AI call (see
app/services/scheduled_job_runner.py).
"""
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app import db, limiter
from app.models.query_log import QueryLog
from app.models.scheduled_job import (
    ScheduledJob, ScheduledJobRun, JOB_TYPES, JOB_TYPE_ALERT, STATUS_ACTIVE, STATUS_PAUSED,
    STATUS_ERROR, ATTACH_FULL, ATTACH_TRIGGERED, TRIGGER_MANUAL,
)
from app.models.user import User, ROLE_ADMIN
from app.services.alert_rules import (
    describe_rule, evaluate_rule, label_columns, normalize_rule, parse_rule_text, suggest_rules,
)
from app.services.audit_service import log_event
from app.services.job_notifications import DEFAULT_TEMPLATES, clean_recipients
from app.services.job_schedule import describe_schedule, next_run_after, normalize_schedule
from app.services.scheduled_job_runner import (
    SCHEDULABLE_TRACKS, execute_job, preview_job, replay_saved_query, send_test,
)
from app.utils.auth_helpers import get_current_user
from app.utils.job_codes import generate_job_code

bp = Blueprint('alerts', __name__, url_prefix='/api/alerts')

PREVIEW_ROWS = 100
UNSUPPORTED_SOURCE = ("Alerts and subscriptions can use database or spreadsheet answers for now. "
                      "This answer came from another kind of source.")
# Where an answer that can't be scheduled actually came from, so the user
# knows what to change in the question.
UNSUPPORTED_SOURCE_REASONS = {
    'MULTI': ("This answer combined more than one data source, so there is no single query to re-run. "
              "Try asking about just the database tables, or just one spreadsheet."),
    'FILES': "This answer came from your files and documents, not from a database or spreadsheet.",
    'API': "This answer came from a live API integration, not from a database or spreadsheet.",
    'GENERAL': ("Saarthi answered this without looking up your data. "
                "Try naming the tables or columns the numbers come from."),
}


def _unsupported_message(router_decision):
    reason = UNSUPPORTED_SOURCE_REASONS.get(router_decision)
    if not reason:
        return UNSUPPORTED_SOURCE
    return "Alerts and subscriptions can use database or spreadsheet answers for now. " + reason


# ------------------------------------------------------------------
# Access
# ------------------------------------------------------------------
def _is_company_admin(user):
    return bool(user and user.role == ROLE_ADMIN and user.company_code)


def _can_manage(user, job):
    if not user or not job:
        return False
    if job.user_id == user.id:
        return True
    return _is_company_admin(user) and job.company_code == user.company_code


def _visible_jobs_query(user):
    query = ScheduledJob.query
    if _is_company_admin(user):
        return query.filter(ScheduledJob.company_code == user.company_code)
    return query.filter(ScheduledJob.user_id == user.id)


def _get_job_or_404(user, job_id):
    job = db.session.get(ScheduledJob, job_id)
    if not _can_manage(user, job):
        return None
    return job


def _error(message, status=400):
    return jsonify({'error': message}), status


# ------------------------------------------------------------------
# Building a job from the create screen's form
# ------------------------------------------------------------------
def _owned_source(owner, query_code):
    """The owner's own Query Logs entry, if it can back a job."""
    if not query_code:
        raise ValueError("Pick the data first: ask a question or choose an existing query.")
    row = QueryLog.query.filter_by(query_code=str(query_code)).first()
    if not row or row.user_id != owner.id:
        raise ValueError("That query was not found in your Query Logs.")
    if row.router_decision not in SCHEDULABLE_TRACKS or not row.main_query:
        raise ValueError(_unsupported_message(row.router_decision))
    return row


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _apply_payload(job, data, owner):
    """Validates the form and writes it onto job (new or existing). Raises
    ValueError with a message for the user."""
    job_type = data.get('job_type', job.job_type)
    if job_type not in JOB_TYPES:
        raise ValueError("Choose Alert or Subscription.")
    if job.id and job_type != job.job_type:
        raise ValueError("An alert can't be turned into a subscription. Duplicate it instead.")
    job.job_type = job_type

    name = str(data.get('name') or '').strip()
    if not name:
        raise ValueError("Give it a name.")
    job.name = name[:200]

    source_code = data.get('source_query_code') or job.source_query_code
    if source_code != job.source_query_code or not job.main_query:
        source = _owned_source(owner, source_code)
        job.source_query_code = source.query_code
        job.question = source.question
        job.router_decision = source.router_decision
        job.main_query = source.main_query
        job.sources = source.sources or []
        job.answer = source.answer
        job.last_value = None
        job.is_triggered = False

    if job_type == JOB_TYPE_ALERT:
        job.rule = normalize_rule(data.get('rule'))
    else:
        job.rule = None

    schedule = normalize_schedule(data.get('schedule'))
    if schedule != job.schedule:
        job.schedule = schedule
        job.next_run_at = next_run_after(schedule, datetime.utcnow())
    elif not job.next_run_at:
        job.next_run_at = next_run_after(schedule, datetime.utcnow())

    try:
        gap = int(data.get('min_gap_minutes') or 0)
    except (TypeError, ValueError):
        raise ValueError("The minimum gap must be a number of minutes.")
    job.min_gap_minutes = max(0, min(gap, 60 * 24 * 366))
    job.notify_once_until_recovered = _bool(data.get('notify_once_until_recovered'))

    job.recipients = clean_recipients(owner, data.get('recipients'))
    defaults = DEFAULT_TEMPLATES[job_type]
    job.subject_template = (str(data.get('subject_template') or '').strip() or defaults['subject'])[:500]
    job.message_template = (str(data.get('message_template') or '').strip() or defaults['message'])[:5000]
    job.attach_excel = _bool(data.get('attach_excel'), True)
    job.attach_scope = ATTACH_FULL if data.get('attach_scope') == ATTACH_FULL else ATTACH_TRIGGERED
    job.include_table = _bool(data.get('include_table'), True)
    job.skip_if_empty = _bool(data.get('skip_if_empty')) if job_type != JOB_TYPE_ALERT else False
    return job


def _draft_from_request(user, data):
    """A job built from the form without saving it - for View sample report
    and Send me a test. With an id, starts from that saved job."""
    job_id = data.get('id')
    if job_id:
        saved = _get_job_or_404(user, job_id)
        if not saved:
            raise LookupError()
        owner = db.session.get(User, saved.user_id)
        draft = ScheduledJob(**{c.name: getattr(saved, c.name) for c in ScheduledJob.__table__.columns})
    else:
        owner = user
        draft = ScheduledJob(user_id=user.id, company_code=user.company_code, status=STATUS_ACTIVE,
                             job_type=data.get('job_type'))
    with db.session.no_autoflush:
        _apply_payload(draft, data, owner)
    if draft in db.session:
        db.session.expunge(draft)
    return draft, owner


def _job_summary(job, owners=None):
    out = job.to_dict()
    out['rule_text'] = describe_rule(job.rule) if job.rule else ''
    out['schedule_text'] = describe_schedule(job.schedule)
    owner = (owners or {}).get(job.user_id)
    out['owner_name'] = owner.name if owner else None
    out['owner_email'] = owner.email if owner else None
    last = (ScheduledJobRun.query.filter_by(job_id=job.id)
            .filter(ScheduledJobRun.trigger != 'test')
            .order_by(ScheduledJobRun.run_at.desc()).first())
    out['last_run'] = last.to_dict() if last else None
    return out


def _source_payload(rows, job_type, question=None, router_decision=None, query_code=None, answer=None):
    rows = rows or []
    payload = {
        'query_code': query_code,
        'question': question,
        'router_decision': router_decision,
        'answer': answer,
        'row_count': len(rows),
        'rows': rows[:PREVIEW_ROWS],
        'supported': router_decision in SCHEDULABLE_TRACKS,
    }
    payload.update(suggest_rules(rows))
    return payload


# ------------------------------------------------------------------
# Settings for the create screen
# ------------------------------------------------------------------
@bp.route('/settings', methods=['GET'])
@jwt_required()
def alert_settings():
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    return jsonify({
        'user_id': user.id,
        'own_email': user.email,
        'default_templates': DEFAULT_TEMPLATES,
        'is_company_admin': _is_company_admin(user),
        'supported_sources': list(SCHEDULABLE_TRACKS),
    })


# ------------------------------------------------------------------
# Picking the data
# ------------------------------------------------------------------
@bp.route('/queries', methods=['GET'])
@jwt_required()
def list_source_queries():
    """The caller's own Query Logs entries that can back a job (database or
    spreadsheet answers with a saved query), newest first. Scheduled runs'
    own rows are left out. ?q= searches the question and query code."""
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    query = (QueryLog.query
             .filter(QueryLog.user_id == user.id)
             .filter(QueryLog.router_decision.in_(SCHEDULABLE_TRACKS))
             .filter(QueryLog.main_query.isnot(None))
             .filter(QueryLog.scheduled_job_id.is_(None)))
    search = (request.args.get('q') or '').strip()
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(QueryLog.question.ilike(like), QueryLog.query_code.ilike(like)))
    rows = query.order_by(QueryLog.created_at.desc()).limit(50).all()
    return jsonify({'queries': [{
        'query_code': r.query_code,
        'question': r.question,
        'router_decision': r.router_decision,
        'run_type': r.run_type or 'Q',
        'created_at': (r.created_at.isoformat() + 'Z') if r.created_at else None,
    } for r in rows]})


@bp.route('/source', methods=['POST'])
@jwt_required()
@limiter.limit("30 per minute")
def load_source():
    """Runs a saved query now (no AI) and returns its latest result plus
    rule suggestions for it. Body: {query_code, job_type, job_id?} - with
    job_id, the query must belong to that job's owner."""
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    data = request.get_json() or {}
    owner = user
    job = None
    if data.get('job_id'):
        job = _get_job_or_404(user, data['job_id'])
        if not job:
            return _error('Alert or subscription not found', 404)
        owner = db.session.get(User, job.user_id)
    if job and data.get('query_code') in (None, '', job.source_query_code):
        # Editing: the job's own copy of its query, even if the Query Logs
        # entry it came from has since been deleted.
        source = job
    else:
        try:
            source = _owned_source(owner, data.get('query_code'))
        except ValueError as e:
            return _error(str(e))
    source_code = source.source_query_code if source is job else source.query_code
    probe = ScheduledJob(user_id=owner.id, router_decision=source.router_decision, main_query=source.main_query,
                         source_query_code=source_code, question=source.question,
                         answer=source.answer, sources=source.sources)
    replay = replay_saved_query(probe)
    if replay['error']:
        return _error(replay['error'], 422)
    return jsonify(_source_payload(replay['rows'], data.get('job_type'), source.question,
                                   source.router_decision, source_code, source.answer))


@bp.route('/ask', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def ask_question():
    """Answers a new question through the normal pipeline with run_type A
    (alert) or S (subscription), then returns it like /source does.
    Body: {question, job_type, model_name?}"""
    from app.routes.chat_routes import resolve_model_credentials, router_service

    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    data = request.get_json() or {}
    question = str(data.get('question') or '').strip()
    if not question:
        return _error('Type a question first.')
    run_type = data.get('job_type') if data.get('job_type') in JOB_TYPES else JOB_TYPE_ALERT
    model_name = str(data.get('model_name') or 'gpt-4o-mini')
    custom_key, _ = resolve_model_credentials(model_name, user.company_code or 'default_company')

    response = router_service.get_smart_response(
        question,
        model_name=model_name,
        session_id=f"alerts-setup-{user.id}",
        custom_key=custom_key,
        system_instructions=user.effective_query_instructions(),
        company_code=user.company_code,
        user_id=user.id,
        run_type=run_type,
    ) or {}
    router_decision = response.get('router_decision')
    query_code = response.get('query_code')
    rows = response.get('table') or []
    payload = _source_payload(rows, run_type, question, router_decision, query_code, response.get('answer'))
    if not query_code:
        payload['supported'] = False
        payload['message'] = "Saarthi couldn't answer that from your data. Try rephrasing the question."
    elif not payload['supported']:
        payload['message'] = _unsupported_message(router_decision)
    return jsonify(payload)


# ------------------------------------------------------------------
# Rules
# ------------------------------------------------------------------
def _rows_from(data):
    rows = data.get('rows')
    return [r for r in rows if isinstance(r, dict)][:500] if isinstance(rows, list) else []


def _rule_llm(user):
    """Reads a rule the plain parser couldn't, once, at setup time."""
    def invoke(prompt):
        import os
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage
        from app.services.llm_call_logger import tracked_invoke
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, openai_api_key=os.getenv("OPENAI_API_KEY"))
        return tracked_invoke(llm, [SystemMessage(content=prompt)], purpose="alerts.rule_parse",
                              model_name="gpt-4o-mini", provider="openai",
                              user_id=user.id, company_code=user.company_code).content
    return invoke


@bp.route('/rules/parse', methods=['POST'])
@jwt_required()
@limiter.limit("30 per minute")
def parse_rule():
    """The user's own words as a rule. Body: {text, rows}"""
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    data = request.get_json() or {}
    rows = _rows_from(data)
    text = str(data.get('text') or '').strip()
    if not text:
        return _error('Describe when Saarthi should tell you.')
    rule = parse_rule_text(text, rows, llm_invoke=_rule_llm(user))
    if not rule:
        return _error("Saarthi couldn't turn that into a rule. Try something like "
                      "\"sales below 5 lakh\" or \"drops more than 10%\".", 422)
    labels = label_columns(rows)
    evaluation = evaluate_rule(rule, rows)
    return jsonify({'rule': rule, 'sentence': describe_rule(rule, labels[0] if labels else None),
                    'evaluation': _evaluation_payload(evaluation)})


@bp.route('/rules/evaluate', methods=['POST'])
@jwt_required()
def evaluate_rule_now():
    """Would this rule fire with these rows? Body: {rule, rows}"""
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    data = request.get_json() or {}
    rows = _rows_from(data)
    try:
        rule = normalize_rule(data.get('rule'))
    except ValueError as e:
        return _error(str(e))
    labels = label_columns(rows)
    return jsonify({'rule': rule, 'sentence': describe_rule(rule, labels[0] if labels else None),
                    'evaluation': _evaluation_payload(evaluate_rule(rule, rows))})


def _evaluation_payload(evaluation):
    return {
        'fired': evaluation['fired'],
        'summary': evaluation['summary'],
        'triggered_count': len(evaluation['triggered_rows']),
        'triggered_labels': evaluation['triggered_labels'][:20],
        'checked': evaluation['checked'],
    }


# ------------------------------------------------------------------
# Sample report and test
# ------------------------------------------------------------------
@bp.route('/preview', methods=['POST'])
@jwt_required()
@limiter.limit("30 per minute")
def preview():
    """View sample report: the email this would send with today's data.
    Sends nothing. Body: the create form (plus id when editing)."""
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    try:
        draft, _ = _draft_from_request(user, request.get_json() or {})
    except LookupError:
        return _error('Alert or subscription not found', 404)
    except ValueError as e:
        return _error(str(e))
    result = preview_job(draft)
    if result.get('error'):
        return _error(result['error'], 422)
    return jsonify(result)


@bp.route('/test', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute")
def test_send():
    """Send me a test: the same email, to the person clicking only."""
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    try:
        draft, _ = _draft_from_request(user, request.get_json() or {})
    except LookupError:
        return _error('Alert or subscription not found', 404)
    except ValueError as e:
        return _error(str(e))
    result = send_test(draft, user)
    if not result['sent']:
        return _error(result.get('error') or 'The test could not be sent.', 422)
    return jsonify(result)


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------
@bp.route('', methods=['GET'])
@bp.route('/', methods=['GET'])
@jwt_required()
def list_jobs():
    """Query params: type (A|S), status (active|paused|error|triggered)."""
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    jobs = _visible_jobs_query(user).order_by(ScheduledJob.created_at.desc()).all()
    counts = {
        'all': len(jobs),
        'A': sum(1 for j in jobs if j.job_type == 'A'),
        'S': sum(1 for j in jobs if j.job_type == 'S'),
        'triggered': sum(1 for j in jobs if j.job_type == 'A' and j.is_triggered),
        'paused': sum(1 for j in jobs if j.status == STATUS_PAUSED),
        'error': sum(1 for j in jobs if j.status == STATUS_ERROR),
    }
    job_type = request.args.get('type')
    if job_type in JOB_TYPES:
        jobs = [j for j in jobs if j.job_type == job_type]
    status = request.args.get('status')
    if status == 'triggered':
        jobs = [j for j in jobs if j.job_type == 'A' and j.is_triggered]
    elif status in (STATUS_ACTIVE, STATUS_PAUSED, STATUS_ERROR):
        jobs = [j for j in jobs if j.status == status]
    owners = {u.id: u for u in User.query.filter(User.id.in_({j.user_id for j in jobs} or {0})).all()}
    return jsonify({'jobs': [_job_summary(j, owners) for j in jobs], 'counts': counts,
                    'is_company_admin': _is_company_admin(user)})


@bp.route('', methods=['POST'])
@bp.route('/', methods=['POST'])
@jwt_required()
def create_job():
    user = get_current_user()
    if not user:
        return _error('Authentication required', 401)
    data = request.get_json() or {}
    job = ScheduledJob(user_id=user.id, company_code=user.company_code, status=STATUS_ACTIVE,
                       job_type=data.get('job_type'))
    try:
        with db.session.no_autoflush:
            _apply_payload(job, data, user)
        job.job_code = generate_job_code(job.job_type)
        db.session.add(job)
        db.session.commit()
    except ValueError as e:
        db.session.rollback()
        return _error(str(e))
    log_event('alert_created' if job.job_type == 'A' else 'subscription_created',
              company_code=user.company_code, user_id=user.id,
              details={'job_code': job.job_code, 'source_query_code': job.source_query_code})
    return jsonify({'job': _job_summary(job, {user.id: user})}), 201


@bp.route('/<int:job_id>', methods=['GET'])
@jwt_required()
def get_job(job_id):
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    owner = db.session.get(User, job.user_id)
    return jsonify({'job': _job_summary(job, {owner.id: owner} if owner else {})})


@bp.route('/<int:job_id>', methods=['PUT'])
@jwt_required()
def update_job(job_id):
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    owner = db.session.get(User, job.user_id)
    try:
        with db.session.no_autoflush:
            _apply_payload(job, request.get_json() or {}, owner)
        db.session.commit()
    except ValueError as e:
        db.session.rollback()
        return _error(str(e))
    log_event('scheduled_job_updated', company_code=user.company_code, user_id=user.id,
              details={'job_code': job.job_code})
    return jsonify({'job': _job_summary(job, {owner.id: owner} if owner else {})})


@bp.route('/<int:job_id>', methods=['DELETE'])
@jwt_required()
def delete_job(job_id):
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    code = job.job_code
    ScheduledJobRun.query.filter_by(job_id=job.id).delete()
    db.session.delete(job)
    db.session.commit()
    log_event('scheduled_job_deleted', company_code=user.company_code, user_id=user.id, details={'job_code': code})
    return jsonify({'status': 'success'})


@bp.route('/<int:job_id>/pause', methods=['POST'])
@jwt_required()
def pause_job(job_id):
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    job.status = STATUS_PAUSED
    db.session.commit()
    return jsonify({'job': _job_summary(job)})


@bp.route('/<int:job_id>/resume', methods=['POST'])
@jwt_required()
def resume_job(job_id):
    """Resume a paused job, or clear an Error so it's back to normal. The
    next run is the next scheduled time from now."""
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    job.status = STATUS_ACTIVE
    job.last_error = None
    job.next_run_at = next_run_after(job.schedule, datetime.utcnow())
    db.session.commit()
    return jsonify({'job': _job_summary(job)})


@bp.route('/<int:job_id>/run', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute")
def run_job_now(job_id):
    """Run now (also Retry for a job in Error): a normal run, outside the
    schedule - same rule, same minimum gap, same recipients."""
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    run = execute_job(job, TRIGGER_MANUAL)
    return jsonify({'run': run.to_dict(), 'job': _job_summary(job)})


@bp.route('/<int:job_id>/duplicate', methods=['POST'])
@jwt_required()
def duplicate_job(job_id):
    """A copy owned by the person duplicating it, paused so it doesn't
    send anything until they've looked at it and resumed it."""
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    skip = {'id', 'job_code', 'created_at', 'updated_at', 'last_run_at', 'last_fired_at',
            'last_value', 'is_triggered', 'last_error'}
    copy = ScheduledJob(**{c.name: getattr(job, c.name) for c in ScheduledJob.__table__.columns if c.name not in skip})
    copy.name = f"Copy of {job.name}"[:200]
    copy.status = STATUS_PAUSED
    if copy.user_id != user.id:
        # An admin duplicating someone else's job gets their own copy.
        copy.user_id, copy.company_code = user.id, user.company_code
    copy.job_code = generate_job_code(copy.job_type)
    db.session.add(copy)
    db.session.commit()
    return jsonify({'job': _job_summary(copy, {user.id: user})}), 201


@bp.route('/<int:job_id>/runs', methods=['GET'])
@jwt_required()
def list_runs(job_id):
    user = get_current_user()
    job = _get_job_or_404(user, job_id)
    if not job:
        return _error('Alert or subscription not found', 404)
    try:
        limit = min(int(request.args.get('limit', 20)), 100)
    except (TypeError, ValueError):
        limit = 20
    runs = (ScheduledJobRun.query.filter_by(job_id=job.id)
            .order_by(ScheduledJobRun.run_at.desc()).limit(limit).all())
    return jsonify({'runs': [r.to_dict() for r in runs]})
