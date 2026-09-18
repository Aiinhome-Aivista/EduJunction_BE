from datetime import datetime, timezone, timedelta

IST_OFFSET = timedelta(hours=5, minutes=30)
IST_TZ = timezone(IST_OFFSET)


def now_ist() -> datetime:
    """Returns current Indian Standard Time (IST) as naive datetime suitable for MySQL DateTime columns."""
    return datetime.now(IST_TZ).replace(tzinfo=None)


def to_iso_ist(dt: datetime | None) -> str:
    """Converts a datetime object to ISO-8601 string with explicit +05:30 timezone offset for frontend JavaScript."""
    if not dt:
        return ""
    if isinstance(dt, str):
        if dt and not ("+" in dt or "Z" in dt):
            return f"{dt}+05:30"
        return dt
    return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
