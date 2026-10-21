"""
Scheduled Job Models - Alerts & Subscriptions.

A ScheduledJob is one alert (job_type 'A': tell people when a rule on the
result is met) or subscription (job_type 'S': send the result on a
schedule). It copies the query it runs from Query Logs at creation time
(question, router_decision, main_query) so a later edit or delete of that
QueryLog row never changes what the job runs.

Scheduled runs replay main_query with no AI call (see
app/services/scheduled_job_runner.py), so only DB and SPREADSHEET answers -
the tracks whose main_query is replayable, router_service.REUSABLE_TRACKS -
can back a job for now.

ScheduledJobRun is one row per run (scheduled, run now, or a test send),
powering the run history on the Reports > Alerts & Subscriptions list.
"""
from datetime import datetime

from app import db

JOB_TYPE_ALERT = 'A'
JOB_TYPE_SUBSCRIPTION = 'S'
JOB_TYPES = (JOB_TYPE_ALERT, JOB_TYPE_SUBSCRIPTION)

STATUS_ACTIVE = 'active'
STATUS_PAUSED = 'paused'
STATUS_ERROR = 'error'

# What the attached Excel holds for an alert: only the rows that met the
# rule, or the full result. Subscriptions always attach the full result.
ATTACH_TRIGGERED = 'triggered'
ATTACH_FULL = 'full'


class ScheduledJob(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'scheduled_jobs'

    id = db.Column(db.Integer, primary_key=True)
    # ALRT00001 / SUBS00001 - same fixed-width style as QUERY00001, see
    # app/utils/job_codes.py.
    job_code = db.Column(db.String(10), unique=True, nullable=False, index=True)
    job_type = db.Column(db.String(1), nullable=False, index=True)  # 'A' alert | 'S' subscription

    # The owner. Every run executes as this user, so it only ever sees data
    # they can already see in chat.
    user_id = db.Column(db.Integer, nullable=False, index=True)
    company_code = db.Column(db.String(50), nullable=True, index=True)

    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(10), nullable=False, default=STATUS_ACTIVE, index=True)

    # The query it runs, copied from Query Logs when the job was created.
    source_query_code = db.Column(db.String(10), nullable=True, index=True)
    question = db.Column(db.Text, nullable=False)
    router_decision = db.Column(db.String(50), nullable=False)
    main_query = db.Column(db.Text, nullable=False)
    sources = db.Column(db.JSON, nullable=True)
    # The answer text stored with the source query - a spreadsheet replay
    # has no LLM-free way to re-phrase it, see _run_reused_spreadsheet_query.
    answer = db.Column(db.Text, nullable=True)

    # Alerts only - see app/services/alert_rules.py for the shape.
    rule = db.Column(db.JSON, nullable=True)

    # {"frequency": hourly|daily|weekly|monthly, "time": "HH:MM", "minute",
    #  "weekday", "day_of_month", "timezone"} - see app/services/job_schedule.py.
    schedule = db.Column(db.JSON, nullable=False)
    next_run_at = db.Column(db.DateTime, nullable=True, index=True)  # UTC

    # Minimum gap between two alert emails. 0 sends on every run the rule
    # is met. notify_once_until_recovered sends once, then stays quiet until
    # a run where the rule is no longer met.
    min_gap_minutes = db.Column(db.Integer, nullable=False, default=0)
    notify_once_until_recovered = db.Column(db.Boolean, nullable=False, default=False)

    recipients = db.Column(db.JSON, nullable=False, default=list)
    subject_template = db.Column(db.Text, nullable=False)
    message_template = db.Column(db.Text, nullable=False)
    attach_excel = db.Column(db.Boolean, nullable=False, default=True)
    attach_scope = db.Column(db.String(10), nullable=False, default=ATTACH_TRIGGERED)
    include_table = db.Column(db.Boolean, nullable=False, default=True)
    # Subscriptions only - don't send when the result has no rows.
    skip_if_empty = db.Column(db.Boolean, nullable=False, default=False)

    last_run_at = db.Column(db.DateTime, nullable=True)
    last_fired_at = db.Column(db.DateTime, nullable=True)
    # Per-row values from the last run, keyed by the row's label - what a
    # "drops more than X% from the last run" rule compares against.
    last_value = db.Column(db.JSON, nullable=True)
    # Whether the rule was met on the last run - drives "only once until it
    # recovers".
    is_triggered = db.Column(db.Boolean, nullable=False, default=False)
    last_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def is_alert(self):
        return self.job_type == JOB_TYPE_ALERT

    def to_dict(self):
        return {
            'id': self.id,
            'job_code': self.job_code,
            'job_type': self.job_type,
            'user_id': self.user_id,
            'company_code': self.company_code,
            'name': self.name,
            'status': self.status,
            'source_query_code': self.source_query_code,
            'question': self.question,
            'router_decision': self.router_decision,
            'main_query': self.main_query,
            'rule': self.rule,
            'schedule': self.schedule,
            'next_run_at': _iso(self.next_run_at),
            'min_gap_minutes': self.min_gap_minutes,
            'notify_once_until_recovered': self.notify_once_until_recovered,
            'recipients': self.recipients or [],
            'subject_template': self.subject_template,
            'message_template': self.message_template,
            'attach_excel': self.attach_excel,
            'attach_scope': self.attach_scope,
            'include_table': self.include_table,
            'skip_if_empty': self.skip_if_empty,
            'last_run_at': _iso(self.last_run_at),
            'last_fired_at': _iso(self.last_fired_at),
            'is_triggered': self.is_triggered,
            'last_error': self.last_error,
            'created_at': _iso(self.created_at),
            'updated_at': _iso(self.updated_at),
        }


RUN_OK = 'ok'            # alert checked, rule not met, nothing sent
RUN_FIRED = 'fired'      # alert rule met, but the minimum gap held the email back
RUN_SENT = 'sent'        # email sent
RUN_SKIPPED = 'skipped'  # subscription with no rows and skip_if_empty
RUN_FAILED = 'failed'

TRIGGER_SCHEDULE = 'schedule'
TRIGGER_MANUAL = 'manual'
TRIGGER_TEST = 'test'


class ScheduledJobRun(db.Model):
    __bind_key__ = 'workspace'
    __tablename__ = 'scheduled_job_runs'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('scheduled_jobs.id', ondelete='CASCADE'), nullable=False, index=True)
    run_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    trigger = db.Column(db.String(10), nullable=False, default=TRIGGER_SCHEDULE)
    # The QueryLog row this run wrote (run_type A/S, scheduled_job_id set).
    query_code = db.Column(db.String(10), nullable=True)
    status = db.Column(db.String(10), nullable=False)
    row_count = db.Column(db.Integer, nullable=True)
    triggered_count = db.Column(db.Integer, nullable=True)
    # Short human summary of what was found, e.g. "2 of 5 rows met the rule: EU, LATAM".
    value = db.Column(db.Text, nullable=True)
    error = db.Column(db.Text, nullable=True)
    notified_to = db.Column(db.JSON, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'run_at': _iso(self.run_at),
            'trigger': self.trigger,
            'query_code': self.query_code,
            'status': self.status,
            'row_count': self.row_count,
            'triggered_count': self.triggered_count,
            'value': self.value,
            'error': self.error,
            'notified_to': self.notified_to or [],
        }


def _iso(value):
    # Stored as naive UTC; say so on the wire so the browser converts it to
    # the viewer's local time instead of treating it as local already.
    return (value.isoformat() + 'Z') if value else None
