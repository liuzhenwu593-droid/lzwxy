"""Timezone utilities for TG Daily Greeter.

Handles conversion between UTC (GitHub Actions runtime) and target
timezones (e.g. Europe/Moscow for Russian friends).
"""

from datetime import datetime, timedelta

import pytz


def now_in_timezone(tz_name: str) -> datetime:
    """Get current time in the specified timezone.

    Args:
        tz_name: IANA timezone name, e.g. 'Europe/Moscow'.

    Returns:
        Timezone-aware datetime.
    """
    tz = pytz.timezone(tz_name)
    return datetime.now(tz)


def is_moscow_timezone(tz_name: str) -> bool:
    """Check if the timezone is Moscow (UTC+3, no DST)."""
    return tz_name == "Europe/Moscow"


def format_datetime(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format a datetime object."""
    return dt.strftime(fmt)


def get_weekday_ru(dt: datetime) -> str:
    """Get Russian weekday name for a datetime.

    Args:
        dt: Timezone-aware datetime.

    Returns:
        Russian weekday name in nominative case, e.g. 'понедельник'.
    """
    weekdays = [
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    ]
    return weekdays[dt.weekday()]


def get_month_ru(dt: datetime) -> str:
    """Get Russian month name in genitive case for date formatting.

    Args:
        dt: Timezone-aware datetime.

    Returns:
        Russian month name in genitive, e.g. 'января'.
    """
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    return months[dt.month - 1]


def format_date_ru(dt: datetime) -> str:
    """Format a date in Russian style, e.g. '27 августа 2026 г.'."""
    return f"{dt.day} {get_month_ru(dt)} {dt.year} г."


def apply_jitter(base_dt: datetime, jitter_minutes: int) -> datetime:
    """Apply a random ±jitter offset to a datetime.

    Args:
        base_dt: The base datetime.
        jitter_minutes: Maximum offset in minutes (positive integer).

    Returns:
        New datetime with random offset applied.
    """
    import random

    if jitter_minutes <= 0:
        return base_dt
    offset = random.randint(-jitter_minutes, jitter_minutes)
    return base_dt + timedelta(minutes=offset)
