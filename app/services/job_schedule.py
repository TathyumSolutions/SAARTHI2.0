"""
When an alert or subscription runs next.

A schedule is stored on ScheduledJob.schedule as:

    {"frequency": "hourly", "minute": 15, "timezone": "Asia/Kolkata"}
    {"frequency": "daily", "time": "09:00", "timezone": "Asia/Kolkata"}
    {"frequency": "weekly", "time": "08:00", "weekday": 0, "timezone": ...}   # 0 = Monday
    {"frequency": "monthly", "time": "09:00", "day_of_month": 2, "timezone": ...}

Times are wall-clock times in the job's own time zone; next_run_after()
returns naive UTC, which is how ScheduledJob.next_run_at is stored. A
monthly day past the end of a short month runs on that month's last day.
"""
import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FREQUENCIES = ("hourly", "daily", "weekly", "monthly")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_TIMEZONE = "UTC"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone: {name}")


def normalize_schedule(raw: Any) -> Dict[str, Any]:
    """A clean schedule, or ValueError naming what is wrong."""
    if not isinstance(raw, dict):
        raise ValueError("Choose how often to run.")
    frequency = raw.get("frequency")
    if frequency not in FREQUENCIES:
        raise ValueError("Choose how often to run: hourly, daily, weekly or monthly.")
    tz_name = str(raw.get("timezone") or DEFAULT_TIMEZONE)
    _zone(tz_name)
    clean: Dict[str, Any] = {"frequency": frequency, "timezone": tz_name}

    if frequency == "hourly":
        minute = _int(raw.get("minute", 0), "minute")
        if not 0 <= minute <= 59:
            raise ValueError("The minute must be between 0 and 59.")
        clean["minute"] = minute
        return clean

    clean["time"] = _parse_time(raw.get("time") or "09:00").strftime("%H:%M")
    if frequency == "weekly":
        weekday = _int(raw.get("weekday", 0), "weekday")
        if not 0 <= weekday <= 6:
            raise ValueError("Choose a day of the week.")
        clean["weekday"] = weekday
    elif frequency == "monthly":
        day = _int(raw.get("day_of_month", 1), "day of the month")
        if not 1 <= day <= 31:
            raise ValueError("The day of the month must be between 1 and 31.")
        clean["day_of_month"] = day
    return clean


def _int(value, label):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"The {label} must be a whole number.")


def _parse_time(value) -> time:
    try:
        hours, minutes = str(value).strip().split(":")[:2]
        return time(int(hours), int(minutes))
    except (TypeError, ValueError):
        raise ValueError("Enter the time as HH:MM, for example 09:00.")


def _to_utc_naive(local_date: date, local_time: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(local_date, local_time).replace(tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)


def next_run_after(schedule: Dict[str, Any], after: datetime) -> datetime:
    """The first run time strictly after `after` (naive UTC), as naive UTC."""
    zone = _zone(schedule.get("timezone"))
    local_now = after.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
    frequency = schedule.get("frequency")

    def first_after(candidates):
        for local_date, local_time in candidates:
            utc = _to_utc_naive(local_date, local_time, zone)
            if utc > after:
                return utc
        raise ValueError("Could not work out the next run time.")

    if frequency == "hourly":
        minute = int(schedule.get("minute", 0))
        start = local_now.replace(minute=0, second=0, microsecond=0)
        return first_after(
            ((start + timedelta(hours=k)).date(), time((start + timedelta(hours=k)).hour, minute))
            for k in range(0, 50)
        )

    at = _parse_time(schedule.get("time") or "09:00")
    if frequency == "daily":
        return first_after((local_now.date() + timedelta(days=k), at) for k in range(0, 3))
    if frequency == "weekly":
        weekday = int(schedule.get("weekday", 0))
        return first_after(
            (local_now.date() + timedelta(days=k), at) for k in range(0, 15)
            if (local_now.date() + timedelta(days=k)).weekday() == weekday
        )
    if frequency == "monthly":
        wanted = int(schedule.get("day_of_month", 1))

        def months():
            year, month = local_now.year, local_now.month
            for _ in range(14):
                last_day = calendar.monthrange(year, month)[1]
                yield date(year, month, min(wanted, last_day)), at
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return first_after(months())
    raise ValueError("Choose how often to run.")


def describe_schedule(schedule: Dict[str, Any]) -> str:
    """e.g. "Daily at 09:00 (Asia/Kolkata)"."""
    if not isinstance(schedule, dict):
        return ""
    frequency = schedule.get("frequency")
    tz_name = schedule.get("timezone") or DEFAULT_TIMEZONE
    if frequency == "hourly":
        return f"Hourly at :{int(schedule.get('minute', 0)):02d} ({tz_name})"
    at = schedule.get("time") or "09:00"
    if frequency == "daily":
        return f"Daily at {at} ({tz_name})"
    if frequency == "weekly":
        return f"Weekly, {WEEKDAYS[int(schedule.get('weekday', 0)) % 7]} at {at} ({tz_name})"
    if frequency == "monthly":
        day = int(schedule.get("day_of_month", 1))
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"Monthly, {day}{suffix} at {at} ({tz_name})"
    return ""


def local_time_text(when: datetime, schedule: Dict[str, Any], fmt: str = "%d %b %Y %H:%M") -> str:
    """A naive-UTC time shown in the job's own time zone."""
    if not when:
        return ""
    try:
        zone = _zone((schedule or {}).get("timezone"))
    except ValueError:
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return when.replace(tzinfo=timezone.utc).astimezone(zone).strftime(fmt)
