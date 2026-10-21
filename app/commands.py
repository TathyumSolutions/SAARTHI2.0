"""
Flask CLI commands.

    flask --app run.py run-due-jobs           # run what's due, then exit (cron, every minute)
    flask --app run.py run-due-jobs --loop    # stay running, wake at the top of every minute

Runs every alert and subscription whose next run time has passed, outside
the gunicorn web workers so a job can't fire once per worker. Overlapping
invocations are safe: each job is claimed before it runs. See
docs/ALERTS_AND_SUBSCRIPTIONS.md for setting it up.
"""
import time
from datetime import datetime

import click
from flask.cli import with_appcontext


def _run_once(limit):
    from app import db
    from app.services.scheduled_job_runner import run_due_jobs

    try:
        runs = run_due_jobs(limit=limit)
        lines = [f"job {run.job_id}: {run.status}" + (f" - {run.error}" if run.error else "") for run in runs]
    except Exception as e:
        # A database blip must not kill the --loop worker; the next minute retries.
        db.session.rollback()
        lines = []
        click.echo(f"{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC: run-due-jobs failed: {e}", err=True)
    finally:
        db.session.remove()
    for line in lines:
        click.echo(f"{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC: {line}")


@click.command('run-due-jobs')
@click.option('--limit', default=100, show_default=True, help='Most jobs to run per minute.')
@click.option('--loop', is_flag=True, help='Keep running and check at the start of every minute.')
@with_appcontext
def run_due_jobs_command(limit, loop):
    """Run alerts and subscriptions that are due."""
    if not loop:
        _run_once(limit)
        return
    click.echo("Alerts & Subscriptions scheduler started; checking at the start of every minute.")
    while True:
        _run_once(limit)
        # Sleep to just past the next minute boundary, so a job set for
        # 09:00 runs at 09:00:01 rather than drifting through the minute.
        time.sleep(60 - (time.time() % 60) + 1)
