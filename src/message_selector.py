"""Message selector for TG Daily Greeter.
Handles:
- Loading message pools from inline config or external YAML files.
- Personal special date detection (birthdays, anniversaries).
- Placeholder substitution ({name}, {date}, {weekday}, {time}).
- Random/sequential message rotation.
"""
import random
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .timezone_utils import format_date_ru, get_weekday_ru


def load_message_pool(target: dict[str, Any], base_dir: Path) -> list[str]:
    """Load the message pool for a target.

    Supports inline 'message_pool' list or 'message_file' path.

    Args:
        target: Target configuration dict.
        base_dir: Base directory for resolving relative message_file paths.

    Returns:
        List of message strings.
    """
    inline = target.get("message_pool")
    if inline and isinstance(inline, list):
        return [str(m) for m in inline if m]

    msg_file = target.get("message_file")
    if msg_file:
        path = Path(msg_file)
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            raise FileNotFoundError(f"Message file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and "messages" in data:
            return [str(m) for m in data["messages"] if m]
        if isinstance(data, list):
            return [str(m) for m in data if m]
        raise ValueError(f"Invalid message file format: {path}")

    return []


def check_special_date(
    target: dict[str, Any], now: datetime, period: str
) -> str | None:
    """Check if today is a personal special date for this target.

    Only personal dates configured in the target's 'special_dates'
    (birthdays, anniversaries, etc.) are detected. Public holidays
    are intentionally NOT auto-greeted.

    On a matched special date, the person ONLY gets the special
    greeting — never a normal morning/evening pool message. If the
    current period has no message configured, it falls back to the
    generic 'message' key, then to the other period's message.

    Args:
        target: Target configuration dict.
        now: Current datetime in the target's timezone.
        period: 'morning' or 'evening'.

    Returns:
        Special date greeting message, or None if no special date.
    """
    date_key = now.strftime("%m-%d")
    target_name = target.get("name", "друг")

    personal_dates = target.get("special_dates", {})
    if not (isinstance(personal_dates, dict) and date_key in personal_dates):
        return None

    entry = personal_dates[date_key]

    if isinstance(entry, str):
        return _apply_placeholders(entry, target_name, now)

    if isinstance(entry, dict):
        # 1. Current period-specific message
        msg = entry.get(period)
        if msg:
            return _apply_placeholders(msg, target_name, now)
        # 2. Generic message (used for both periods)
        msg = entry.get("message")
        if msg:
            return _apply_placeholders(msg, target_name, now)
        # 3. Fallback to the other period's message
        other = "evening" if period == "morning" else "morning"
        msg = entry.get(other)
        if msg:
            return _apply_placeholders(msg, target_name, now)

    # Date is in special_dates but nothing usable is configured
    return None


def select_message(
    messages: list[str],
    target_name: str,
    now: datetime,
    selection_mode: str = "random",
) -> str:
    """Select a message from the pool and apply placeholders.

    Args:
        messages: List of message templates.
        target_name: Name of the recipient for {name} placeholder.
        now: Current datetime in target timezone.
        selection_mode: 'random' or 'sequential'.

    Returns:
        Final message string with placeholders substituted.
    """
    if not messages:
        return ""

    if selection_mode == "sequential":
        # Use day-of-year to pick deterministically
        idx = now.timetuple().tm_yday % len(messages)
        template = messages[idx]
    else:
        template = random.choice(messages)

    return _apply_placeholders(template, target_name, now)


def select_messages_batch(
    targets_data: list[dict[str, Any]],
    now: datetime,
) -> list[str]:
    """Select messages for multiple targets, ensuring no duplicates within
    targets that share the same message pool.

    Targets using different message pools are independent. Targets sharing
    the same pool get unique messages if the pool is large enough.

    Args:
        targets_data: List of dicts, each with:
            - 'target': target config dict (needs 'name')
            - 'messages': loaded message pool list
            - 'selection_mode': 'random' or 'sequential'
        now: Current datetime in the relevant timezone.

    Returns:
        List of selected message strings, same order as targets_data.
    """
    if not targets_data:
        return []

    results: list[str | None] = [None] * len(targets_data)

    # Group target indices by their message pool content
    groups: dict[tuple[str, ...], list[int]] = {}
    for i, item in enumerate(targets_data):
        pool_key = tuple(sorted(item["messages"]))
        groups.setdefault(pool_key, []).append(i)

    for pool_key, indices in groups.items():
        pool = list(pool_key)
        first_item = targets_data[indices[0]]
        selection_mode = first_item.get("selection_mode", "random")

        if not pool:
            for idx in indices:
                results[idx] = ""
            continue

        if selection_mode == "sequential":
            for offset, idx in enumerate(indices):
                day_idx = (now.timetuple().tm_yday + offset) % len(pool)
                template = pool[day_idx]
                target_name = targets_data[idx]["target"].get("name", "друг")
                results[idx] = _apply_placeholders(template, target_name, now)
        else:
            # Random: sample without replacement if pool large enough
            if len(pool) >= len(indices):
                selected = random.sample(pool, len(indices))
            else:
                selected = random.sample(pool, len(pool))
                selected += [
                    random.choice(pool)
                    for _ in range(len(indices) - len(pool))
                ]

            for idx, template in zip(indices, selected):
                target_name = targets_data[idx]["target"].get("name", "друг")
                results[idx] = _apply_placeholders(template, target_name, now)

    return [r if r is not None else "" for r in results]


def _apply_placeholders(template: str, name: str, now: datetime) -> str:
    """Substitute placeholders in a message template.

    Supported placeholders:
    - {name}: recipient name
    - {date}: Russian-formatted date (e.g. '27 августа 2026 г.')
    - {weekday}: Russian weekday name
    - {time}: current time HH:MM
    - {day}: day of month (number)
    - {month}: Russian month name (genitive)
    - {year}: year (number)
    """
    return (
        template.replace("{name}", name)
        .replace("{date}", format_date_ru(now))
        .replace("{weekday}", get_weekday_ru(now))
        .replace("{time}", now.strftime("%H:%M"))
        .replace("{day}", str(now.day))
        .replace("{month}", _month_name_genitive(now))
        .replace("{year}", str(now.year))
    )


def _month_name_genitive(now: datetime) -> str:
    """Get Russian month name in genitive case."""
    months = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ]
    return months[now.month - 1]
