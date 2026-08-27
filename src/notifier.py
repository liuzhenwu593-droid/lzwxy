"""Execution notifier for TG Daily Greeter.

Sends a summary report to the user's Saved Messages after each run,
so the user can verify what was sent and to whom.
"""

from datetime import datetime
from typing import Any

from .telegram_sender import TelegramSender
from .timezone_utils import format_datetime


async def send_execution_report(
    sender: TelegramSender,
    period: str,
    results: list[dict[str, Any]],
    run_time: datetime,
    dry_run: bool = False,
) -> None:
    """Send an execution summary to Saved Messages.

    Args:
        sender: Connected TelegramSender instance.
        period: 'morning' or 'evening'.
        results: List of send result dicts.
        run_time: Datetime when the run started.
        dry_run: Whether this was a dry run (no actual messages sent).
    """
    period_ru = "Утро" if period == "morning" else "Вечер"
    prefix = "[DRY-RUN] " if dry_run else ""

    success_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - success_count

    lines = [
        f"{prefix}📋 {period_ru} — отчёт о рассылке",
        f"⏰ Время: {format_datetime(run_time)}",
        f"✅ Успешно: {success_count} | ❌ Ошибок: {fail_count}",
        "",
    ]

    for i, r in enumerate(results, 1):
        target = r.get("target", "?")
        status = "✅" if r.get("success") else "❌"
        msg_preview = (r.get("message", "")[:60] + "...") if len(r.get("message", "")) > 60 else r.get("message", "")
        lines.append(f"{i}. {status} {target}")
        lines.append(f"   └─ {msg_preview}")
        if not r.get("success"):
            lines.append(f"   └─ Ошибка: {r.get('error', 'unknown')}")

    lines.append("")
    lines.append("— TG Daily Greeter")

    report = "\n".join(lines)

    try:
        await sender.send_to_self(report)
        print(f"\n[Notifier] Execution report sent to Saved Messages.")
    except Exception as e:
        print(f"\n[Notifier] Failed to send report: {e}")
