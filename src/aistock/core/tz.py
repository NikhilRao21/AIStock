from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional


def _get_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # Fallback to UTC if the named zone isn't available in the environment
        return ZoneInfo("UTC")


def format_iso_in_tz(dt: Optional[datetime], tz_name: str = "America/New_York") -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    tz = _get_zone(tz_name)
    try:
        localized = dt.astimezone(tz)
    except Exception:
        # If conversion fails, return the original isoformat
        return dt.isoformat()
    return localized.isoformat()


def format_human_in_tz(
    dt: Optional[datetime], tz_name: str = "America/New_York", fmt: str = "%b %d, %Y %I:%M %p %Z"
) -> Optional[str]:
    """Return a human-friendly formatted datetime string in the given timezone.

    Default format: "Apr 14, 2026 09:00 AM EDT".
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz = _get_zone(tz_name)
    try:
        localized = dt.astimezone(tz)
    except Exception:
        return dt.isoformat()
    return localized.strftime(fmt)


def to_zone(dt: Optional[datetime], tz_name: str = "America/New_York") -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    tz = _get_zone(tz_name)
    return dt.astimezone(tz)


def is_market_open(
    now: Optional[datetime] = None,
    tz_name: str = "America/New_York",
    open_hhmm: str = "09:30",
    close_hhmm: str = "16:00",
) -> bool:
    """Return True if the given (or current) time is within market hours in the given timezone.

    open_hhmm and close_hhmm are strings like "09:30" and "16:00".
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tz = _get_zone(tz_name)
    local = now.astimezone(tz)

    open_h, open_m = (int(x) for x in open_hhmm.split(":"))
    close_h, close_m = (int(x) for x in close_hhmm.split(":"))

    open_dt = local.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_dt = local.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    return open_dt <= local < close_dt
