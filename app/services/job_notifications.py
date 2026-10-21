"""
What alert and subscription emails say, and who they may go to.

Recipients can be any email address, inside or outside the company (the
project owner's call); they are only checked to be well-formed addresses.

Subjects and messages are templates with fill-ins in braces, filled from
the run: {name}, {question}, {run_date}, {run_time}, {row_count},
{triggered_count}, {triggered_list}, {rule}, {value}, {threshold},
{gap_percent}, {query_code}, {link}, and any column of the first row that
met the rule (or the first row, for subscriptions) such as {region} or
{sales_amount}. {first_row.<column>} names a column explicitly. A fill-in
that doesn't exist is left as typed, so it shows up in the sample report.
"""
import html as html_lib
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.alert_rules import describe_rule, label_columns, to_number, _format_number
from app.services.job_schedule import local_time_text

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MAX_RECIPIENTS = 50
MAX_TABLE_ROWS = 50
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

DEFAULT_TEMPLATES = {
    "A": {
        "subject": "Saarthi alert: {name}",
        "message": "{name}: {triggered_count} of {row_count} rows met the rule \"{rule}\" on {run_date}.\n"
                   "Rows that met it: {triggered_list}.",
    },
    "S": {
        "subject": "Saarthi: {name} for {run_date}",
        "message": "Hi, here is {name} for {run_date}. It has {row_count} rows.",
    },
}


# ------------------------------------------------------------------
# Recipients
# ------------------------------------------------------------------
def clean_recipients(owner, raw) -> List[str]:
    """Validated, de-duplicated, lower-cased recipient list, or ValueError
    naming an address that isn't one. "me" stands for the owner."""
    if isinstance(raw, str):
        raw = re.split(r"[,;\s]+", raw)
    emails, seen = [], set()
    for item in raw or []:
        email = str(item or "").strip().lower()
        if email in ("me", "you"):
            email = (owner.email or "").lower()
        if not email or email in seen:
            continue
        if not EMAIL_RE.match(email):
            raise ValueError(f"{email} is not an email address.")
        seen.add(email)
        emails.append(email)
    if not emails:
        raise ValueError("Add at least one person to send it to.")
    if len(emails) > MAX_RECIPIENTS:
        raise ValueError(f"Send to at most {MAX_RECIPIENTS} addresses.")

    return emails


# ------------------------------------------------------------------
# Fill-ins
# ------------------------------------------------------------------
_FILL_IN_RE = re.compile(r"\{([A-Za-z_][\w .-]*)\}")


def _display(value: Any) -> str:
    if value is None:
        return ""
    number = to_number(value) if not isinstance(value, str) else None
    if number is not None:
        return _format_number(number)
    return str(value)


def app_link(path: str = "") -> str:
    base = (os.getenv("APP_BASE_URL") or "").rstrip("/")
    return f"{base}{path}" if base else ""


def build_fill_ins(job, rows: List[Dict[str, Any]], evaluation: Optional[Dict[str, Any]],
                   run_time: datetime) -> Dict[str, str]:
    rows = rows or []
    labels = label_columns(rows)
    values: Dict[str, str] = {
        "name": job.name or "",
        "question": job.question or "",
        "run_date": local_time_text(run_time, job.schedule, "%d %b %Y"),
        "run_time": local_time_text(run_time, job.schedule, "%d %b %Y %H:%M"),
        "row_count": str(len(rows)),
        "query_code": job.source_query_code or "",
        "link": app_link("/alerts"),
    }
    first = rows[0] if rows else {}
    if evaluation is not None and job.rule:
        rule = job.rule
        triggered = evaluation.get("triggered_rows") or []
        values["rule"] = describe_rule(rule, labels[0] if labels else None)
        values["triggered_count"] = str(len(triggered))
        values["triggered_list"] = ", ".join(str(r.get("_label")) for r in triggered[:20]) or "none"
        values["threshold"] = _display(rule.get("value")) if rule.get("kind") in ("threshold", "row_count") else ""
        if triggered:
            first = triggered[0]
            values["value"] = _display(first.get(rule.get("column")))
            if rule.get("kind") in ("compare", "pct_vs_column"):
                values["threshold"] = _display(first.get(rule.get("compare_column")))
            gap = first.get("_gap_percent")
            values["gap_percent"] = f"{abs(gap):.1f}%" if gap is not None else ""
    else:
        values["triggered_count"] = str(len(rows))
        values["triggered_list"] = ", ".join(
            str(r.get(labels[0])) for r in rows[:20] if labels) if labels else ""

    for column, value in (first or {}).items():
        if str(column).startswith("_"):
            continue
        values.setdefault(str(column), _display(value))
        values[f"first_row.{column}"] = _display(value)
    values.setdefault("value", "")
    values.setdefault("threshold", "")
    values.setdefault("gap_percent", "")
    values.setdefault("rule", "")
    return values


def render_text(template: str, values: Dict[str, str]) -> str:
    return _FILL_IN_RE.sub(lambda m: values.get(m.group(1).strip(), m.group(0)), template or "")


# ------------------------------------------------------------------
# The email
# ------------------------------------------------------------------
def _clean_rows(rows):
    return [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in rows]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "report").strip("_")[:40] or "report"


def build_email(job, rows: List[Dict[str, Any]], evaluation: Optional[Dict[str, Any]],
                run_time: datetime, is_test: bool = False) -> Dict[str, Any]:
    """Subject, plain text, HTML and the optional Excel attachment for one
    run. For alerts, the table and attachment hold only the rows that met
    the rule when attach_scope is 'triggered' (and the rule fired)."""
    from app.services.result_export_service import build_result_workbook

    values = build_fill_ins(job, rows, evaluation, run_time)
    defaults = DEFAULT_TEMPLATES.get(job.job_type, DEFAULT_TEMPLATES["S"])
    subject = render_text(job.subject_template or defaults["subject"], values).replace("\n", " ").strip()
    message = render_text(job.message_template or defaults["message"], values)
    if is_test:
        subject = f"[Test] {subject}"

    triggered = (evaluation or {}).get("triggered_rows") or []
    use_triggered = job.job_type == "A" and job.attach_scope == "triggered" and triggered
    table_rows = _clean_rows(triggered if use_triggered else rows)
    columns: List[str] = []
    for row in table_rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    attachment = None
    if job.attach_excel and table_rows:
        workbook = build_result_workbook({
            "columns": columns, "rows": table_rows, "question": job.question,
            "created_at": run_time.isoformat(timespec="seconds"),
        })
        filename = f"{_slug(job.name)}_{local_time_text(run_time, job.schedule, '%Y-%m-%d')}.xlsx"
        attachment = (filename, workbook.getvalue(), XLSX_MIME)

    kind = "Alert" if job.job_type == "A" else "Subscription"
    footer = f"Question: {job.question}" + (f" ({job.source_query_code})" if job.source_query_code else "")
    manage_link = app_link("/alerts")

    text_parts = [message, ""]
    if job.include_table and table_rows:
        text_parts.append(f"{len(table_rows)} row(s)" + (" attached as Excel." if attachment else "."))
    text_parts += ["", footer]
    if manage_link:
        text_parts.append(f"Manage your alerts and subscriptions: {manage_link}")

    html = _render_html(job, kind, message, columns, table_rows if job.include_table else [],
                        attachment[0] if attachment else None, values, footer, manage_link, is_test)
    return {
        "subject": subject,
        "text": "\n".join(text_parts).strip(),
        "html": html,
        "attachment": attachment,
        "attachment_name": attachment[0] if attachment else None,
        "row_count": len(rows or []),
        "table_row_count": len(table_rows),
    }


def _render_html(job, kind, message, columns, table_rows, attachment_name, values, footer, manage_link, is_test):
    esc = html_lib.escape
    paragraphs = "".join(
        f'<p style="margin:0 0 10px;">{esc(p)}</p>' for p in message.split("\n") if p.strip()
    )
    table = ""
    if table_rows:
        head = "".join(
            f'<th style="padding:8px 10px;text-align:left;background:#2563EB;color:#fff;font-size:12px;">{esc(str(c))}</th>'
            for c in columns
        )
        body = "".join(
            "<tr>" + "".join(
                f'<td style="padding:7px 10px;border-bottom:1px solid #E5E5E5;font-size:13px;">{esc(_display(r.get(c)))}</td>'
                for c in columns
            ) + "</tr>"
            for r in table_rows[:MAX_TABLE_ROWS]
        )
        more = ""
        if len(table_rows) > MAX_TABLE_ROWS:
            more = (f'<p style="margin:6px 0 0;font-size:12px;color:#5A5A5A;">'
                    f'{len(table_rows) - MAX_TABLE_ROWS} more row(s)'
                    f'{" in the attached file" if attachment_name else ""}.</p>')
        table = (f'<table style="width:100%;border-collapse:collapse;margin:6px 0;">'
                 f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{more}')
    attachment = (f'<p style="margin:10px 0 0;font-size:13px;">Attached: {esc(attachment_name)}</p>'
                  if attachment_name else "")
    test_note = ('<p style="margin:0 0 10px;padding:6px 10px;background:#FFF4E5;border-radius:4px;font-size:12px;">'
                 'This is a test. Only you received it.</p>' if is_test else "")
    link = (f' &middot; <a href="{esc(manage_link)}" style="color:#0B5CAD;">Manage alerts and subscriptions</a>'
            if manage_link else "")
    return (
        '<div style="font-family:Segoe UI,Arial,sans-serif;color:#1E1E1E;max-width:720px;">'
        f'{test_note}'
        f'<div style="font-size:15px;font-weight:600;margin-bottom:2px;">{esc(job.name or "")}</div>'
        f'<div style="font-size:12px;color:#5A5A5A;margin-bottom:14px;">{kind} &middot; {esc(values.get("run_time", ""))}</div>'
        f'{paragraphs}{table}{attachment}'
        f'<div style="margin-top:16px;padding-top:10px;border-top:1px solid #E5E5E5;font-size:12px;color:#5A5A5A;">'
        f'{esc(footer)}{link}</div></div>'
    )
