"""Strict field conversion with errors that never include source values."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings


def integer(value, location, min_value=1):
    try:
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise ValueError
        number = int(value)
        if not min_value <= number <= 9223372036854775807:
            raise ValueError
        return number
    except (ValueError, TypeError):
        raise ValueError(f"{location}: invalid integer") from None


def boolean(value, location):
    if value not in ("t", "f"):
        raise ValueError(f"{location}: invalid boolean")
    return value == "t"


def bounded_text(value, location, max_length, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > max_length or "\x00" in value:
        raise ValueError(f"{location}: invalid or oversized text")
    return value


def timestamp(value, location, nullable=False):
    if value is None and nullable:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        if not settings.USE_TZ:
            parsed = parsed.astimezone(ZoneInfo(settings.TIME_ZONE)).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{location}: invalid timezone-aware timestamp") from None
