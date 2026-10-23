# Alerts & Subscriptions

An **alert** re-runs a saved query on a schedule and emails people when a rule on
the result is met ("sales falls below budget for any region"). A
**subscription** re-runs it on a schedule and emails the result every time.

## Where it lives

| Menu | Page | What it does |
|---|---|---|
| Management › Alerts & Subscriptions | `/alerts/new` | The create screen, for every user. Alert/Subscription radio at the top. |
| Reports › Alerts & Subscriptions | `/alerts` | The list: filters, edit, run now, pause/resume, duplicate, delete, and each job's recent runs. |
| Query Logs | `/query_logs` | Your own database/spreadsheet answers get a "Set up an alert on this" link. A Run filter shows questions, alert runs and subscription runs separately. |

There is no Subscribe button in chat (`tests/test_chat_no_subscribe.py` enforces it).

**Who can manage what:** every user manages their own alerts and subscriptions;
a company admin sees and manages every job in their company. A job always runs
as its owner, so it only sees data the owner can see in chat, whoever edits it.

**Recipients:** any email addresses. `me` means the person setting it up.

## The create screen

1. **Which data?** Either *ask a new question* (answered by the normal pipeline,
   `RouterService.get_smart_response`, with `run_type` `A` or `S`), or *use an
   existing query* from your Query Logs. Only database and spreadsheet answers
   can be scheduled for now, because they are the ones a scheduled run can
   replay without AI. A question asked here tells the router to answer with a
   single database (or spreadsheet) query that joins every table it needs, and
   if the router still splits it into one database call per table, those calls
   are merged back into one. When an answer still can't be scheduled, the
   screen says where it came from (several sources, files, an API, or no data
   at all).
2. **When should Saarthi tell you?** (alerts) Saarthi reads the result's columns
   and suggests rules that fit, for example *sales_amount falls below
   budget_amount*, *more than 10% below budget*, *drops more than 15% from the
   last run*, *goes below a fixed amount*, *the result has any rows*. Cost-like
   columns (cost, overdue, defects, ...) get "goes above" instead. You can also
   type the rule in your own words ("tell me if APAC sales drops below 5 lakh");
   common phrasings are read without AI, and an LLM is asked once, only if that
   fails. The rule is shown as a sentence with clickable parts, plus how many rows
   would trigger with today's data. Check *each row* or *the total*.
3. **Standard settings:** name, how often (hourly, daily, weekly, monthly, at a
   time in your browser's time zone), the minimum gap between two alerts (or
   *only once until it recovers*), recipients, subject and message with
   fill-ins, and the Excel attachment (rows that triggered, or the full result).

**View sample report** shows the exact email with today's data and sends
nothing. **Send me a test now** sends that email to you only.

Fill-ins: `{name} {question} {run_date} {run_time} {row_count} {rule}
{triggered_count} {triggered_list} {value} {threshold} {gap_percent}
{query_code} {link}` and any column of the first row that met the rule (the
first row, for subscriptions), such as `{region}`.

## How a run works

1. `flask run-due-jobs` finds active jobs whose `next_run_at` has passed, and
   claims each one by moving `next_run_at` to the next scheduled time with a
   conditional UPDATE. Two scheduler processes can never run the same job twice.
2. The job's saved query (copied from Query Logs when the job was created) is
   replayed **with no AI call** through the same functions chat uses to replay
   a liked query: `_run_reused_db_query` (the stored SQL; the insight LLM call
   is skipped) or `_run_reused_spreadsheet_query` (the stored plan).
3. The run is logged to Query Logs with `run_type` `A`/`S` and `scheduled_job_id`.
4. Alerts: the rule is checked in plain Python (`app/services/alert_rules.py`),
   then the minimum gap / "once until it recovers" setting decides whether to email.
5. A row is written to `scheduled_job_runs` (shown under *Recent runs*).

If a run fails (database unreachable, query no longer valid, email failed) the
job shows **Error** and the owner gets one email about it, not the recipients.
It keeps running on schedule and goes back to normal on the next run that works.
**Retry** runs it now. A job that missed runs while the scheduler was down runs
once when it comes back, then continues on schedule.

## Setting up the scheduler

The scheduler runs outside the web workers, so a job can't fire once per gunicorn
worker. Run **exactly one** of these.

### Docker Compose (recommended)

`docker-compose.yml` has a `scheduler` service:

```
flask --app run.py run-due-jobs --loop
```

It stays running and wakes at the start of every minute, so a job set for 09:00
runs at about 09:00:01. `docker compose up -d` starts it with the rest.

### cron

Without Docker, run the one-shot command every minute:

```
* * * * * cd /path/to/SAARTHI2.0 && FLASK_ENV=production /path/to/venv/bin/flask --app run.py run-due-jobs >> /var/log/saarthi-jobs.log 2>&1
```

Each invocation starts the app first (a few seconds), so jobs run a few seconds
after the minute. Overlapping invocations are safe.

### Environment

The scheduler needs the same environment as the web app (`DATABASE_URL`, model
keys) plus:

| Variable | Purpose |
|---|---|
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | Sending the emails (see `app/services/email_service.py`). Without `SMTP_HOST`, emails are written to the log instead. |
| `APP_BASE_URL` | e.g. `https://saarthi.example.com`, for the "Manage alerts and subscriptions" link in each email. Optional. |

## Data model

- `query_logs.run_type` (`Q` regular / `A` alert / `S` subscription, default `Q`)
  and `query_logs.scheduled_job_id`.
- `scheduled_jobs`: one row per alert (`ALRT00001`) or subscription (`SUBS00001`).
- `scheduled_job_runs`: one row per run (`ok`, `fired` (met but held back by the
  gap), `sent`, `skipped`, `failed`; trigger `schedule`, `manual` or `test`).

Tables and columns are created on startup by `db.create_all()` and
`sync_missing_columns()`, like every other model.

## API

All under `/api/alerts`, JWT required.

| Method | Path | |
|---|---|---|
| GET | `/settings` | Your email and the default templates |
| GET | `/queries?q=` | Your Query Logs entries that can back a job |
| POST | `/source` | Run a saved query now; result plus rule suggestions |
| POST | `/ask` | Ask a new question (run_type A/S); same shape as `/source` |
| POST | `/rules/parse`, `/rules/evaluate` | Own words to rule; would it fire today |
| POST | `/preview`, `/test` | Sample report; send me a test |
| GET, POST | `/` | List (filters `type`, `status`), create |
| GET, PUT, DELETE | `/<id>` | Read, edit, delete |
| POST | `/<id>/pause`, `/<id>/resume`, `/<id>/run`, `/<id>/duplicate` | Actions |
| GET | `/<id>/runs` | Run history |

`POST /api/chat/message` also accepts `run_type` (`Q` default, `A`, `S`).

## Not in this version

In-app notifications, Teams/Slack, and alerts on files, API or multi-source
answers (these can't be replayed without AI yet).
