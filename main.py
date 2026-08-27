#!/usr/bin/env python3
"""TG Daily Greeter - Main entry point.
Sends daily morning/evening greeting messages to configured targets
using a personal Telegram account. Designed to run as a short-lived
GitHub Actions workflow (manual trigger only).

Features:
- Auto period detection: 0:00~12:59 MSK = morning, 13:00~23:59 MSK = evening
  (or specify explicitly with --period)
- Morning: run any time in 0:00~12:59 MSK, wait 1~5 min, then send morning
- Evening: run any time in 13:00~23:59 MSK, wait 1~5 min, then send evening
- 20% daily skip probability (human-like)
- Per-target random delay 2~5s between sends
- Typing indicator simulation 1.5~4s
- Realistic device fingerprint rotation
- No duplicate messages across targets
- Personal special dates (birthdays) only — no public holiday auto-greetings
- On a birthday, the person ONLY gets birthday greetings (never normal pool)
- FloodWait auto-retry (max 2), user fatal errors no-retry
- Global 300s connection+sending timeout
- Set offline status before disconnect
- Clean emoji-formatted console output

Usage:
    python main.py                          # auto-detect period by Moscow time
    python main.py --period morning         # explicit morning
    python main.py --period evening         # explicit evening
    python main.py --period morning --dry-run
    python main.py --period morning --no-skip --no-delay --dry-run
"""
import argparse
import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path

from src.config_loader import ConfigError, load_config
from src.message_selector import (
    check_special_date,
    load_message_pool,
    select_messages_batch,
)
from src.notifier import send_execution_report
from src.telegram_sender import TelegramSender
from src.timezone_utils import now_in_timezone

# Global timeout for the entire connect + send + disconnect phase
GLOBAL_SEND_TIMEOUT = 300  # seconds

# Friendly timezone display names
_TZ_DISPLAY = {
    "Europe/Moscow": "莫斯科",
    "Europe/Chisinau": "摩尔多瓦",
    "Europe/Kiev": "基辅",
    "Europe/Minsk": "明斯克",
}


def tz_display_name(tz_name: str) -> str:
    """Get a friendly display name for a timezone."""
    return _TZ_DISPLAY.get(tz_name, tz_name)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="TG Daily Greeter - Send daily greetings via Telegram user account."
    )
    parser.add_argument(
        "--period",
        choices=["morning", "evening"],
        default=None,
        help="Which greeting period to send: 'morning' or 'evening'. "
        "If omitted, auto-detected from current Moscow time "
        "(0:00~12:59 = morning, 13:00~23:59 = evening).",
    )
    parser.add_argument(
        "--config",
        default="config/config.yml",
        help="Path to configuration YAML file (default: config/config.yml).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print messages without actually sending them.",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Only send to a specific target name (for testing).",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Ignore the daily skip probability (always run).",
    )
    parser.add_argument(
        "--no-delay",
        action="store_true",
        help="Skip all delays (send window + inter-target delays, for testing).",
    )
    return parser.parse_args()


def detect_period(now_tz: datetime) -> str | None:
    """Auto-detect greeting period from current time.

    Morning: 0:00 ~ 12:59 (inclusive)
    Evening: 13:00 ~ 23:59 (inclusive)
    Every hour belongs to a window, so this never returns None.

    Args:
        now_tz: Current datetime in the configured timezone.

    Returns:
        'morning', 'evening', or None.
    """
    hour = now_tz.hour
    if hour <= 12:
        return "morning"
    if hour <= 23:
        return "evening"
    return None


def should_skip_today(skip_probability: float) -> bool:
    """Determine whether to skip sending today based on probability.

    Prints the random roll and the threshold so the result is fully
    transparent and easy to debug.

    Args:
        skip_probability: 0.0~1.0 probability of skipping (NOT sending) today.

    Returns:
        True if today should be skipped (no messages sent).
    """
    if skip_probability <= 0:
        print("🎲 跳过概率 = 0，今天总是发送")
        return False
    roll = random.random()
    skipped = roll < skip_probability
    print(
        f"🎲 概率判定: 随机数={roll:.4f}, 跳过阈值={skip_probability:.2f}"
        f" ({skip_probability:.0%}), {'命中 → 今日跳过' if skipped else '未命中 → 今日发送'}"
    )
    return skipped


def get_period_config(target: dict, period: str) -> dict:
    """Get period-specific message config, falling back to top-level."""
    period_cfg = target.get(period)
    if isinstance(period_cfg, dict) and (
        period_cfg.get("message_pool") or period_cfg.get("message_file")
    ):
        return {**target, **period_cfg}
    return target


def get_delay_range(cfg: dict, period: str) -> tuple[int, int]:
    """Get the pre-send random delay range (seconds) for the given period.

    Both morning and evening use a short random wait (default 1~5 minutes)
    so the actual send happens shortly after the workflow triggers.

    Returns:
        Tuple of (min_seconds, max_seconds).
    """
    if period == "morning":
        return (
            int(cfg.get("morning_delay_min", 60)),
            int(cfg.get("morning_delay_max", 300)),
        )
    else:
        return (
            int(cfg.get("evening_delay_min", 60)),
            int(cfg.get("evening_delay_max", 300)),
        )


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds}秒"
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    if minutes < 60:
        if remaining_seconds == 0:
            return f"{minutes}分钟"
        return f"{minutes}分钟{remaining_seconds}秒"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes == 0:
        return f"{hours}小时"
    return f"{hours}小时{remaining_minutes}分钟"


async def run(args: argparse.Namespace) -> int:
    """Main execution logic."""
    project_root = Path(__file__).resolve().parent
    config_path = project_root / args.config

    # Load configuration
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        print(f"❌ 配置错误: {e}")
        return 1

    dry_run = args.dry_run or cfg.get("dry_run", False)
    tz_name = cfg.get("timezone", "Europe/Moscow")
    now_tz = now_in_timezone(tz_name)

    # ── Period resolution (explicit flag or auto-detect) ───
    if args.period:
        period = args.period
    else:
        period = detect_period(now_tz)
        if period is None:
            print(f"▶ Run python main.py")
            print(f"🕐 当前时间: {now_tz.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name})")
            print(
                f"❌ 当前时间 ({now_tz.hour}:{now_tz.minute:02d}) 不在发送窗口内。\n"
                f"   早上窗口: 00:00~12:59\n"
                f"   晚上窗口: 13:00~23:59\n"
                f"   请使用 --period morning 或 --period evening 强制指定。"
            )
            return 1

    period_cn = "早上" if period == "morning" else "晚上"

    # ── Header ──────────────────────────────────────────────
    print("▶ Run python main.py")

    # ── Step 1: Daily skip probability ──────────────────────
    skip_prob = cfg.get("skip_probability", 0.2)
    if not args.no_skip and not dry_run:
        if should_skip_today(skip_prob):
            print(f"🎲 今日随机跳过 (概率 {skip_prob:.0%})，不发送任何消息")
            if skip_prob > 0.5:
                print(
                    f"⚠️  提示: 当前 skip_probability={skip_prob:.0%}，意味着约 "
                    f"{skip_prob:.0%} 的天数会跳过发送。"
                    f"若你频繁遇到跳过，请检查 config.yml 中 skip_probability 的值"
                    f"（0=总是发送；如需少量发送，建议保持 0.2 左右）。"
                )
            print("🏁 脚本执行完毕")
            return 0
        else:
            print(f"🎲 今日未跳过 (概率 {skip_prob:.0%})，继续执行")
    elif args.no_skip:
        print("🎲 --no-skip 已启用，忽略跳过概率")
    else:
        print("🎲 试运行模式，跳过概率检查")

    # ── Step 2: Filter targets ───────────────────────────────
    targets = cfg["targets"]
    if args.target:
        targets = [t for t in targets if t.get("name") == args.target]
        if not targets:
            print(f"❌ 未找到目标: {args.target}")
            return 1

    print(f"👤 准备发送消息给 {len(targets)} 个用户")
    for t in targets:
        print(f"   • {t['name']}")

    # ── Step 3: Random sleep within send window ─────────────
    delay_min, delay_max = get_delay_range(cfg, period)
    if not args.no_delay and not dry_run:
        sleep_seconds = random.randint(delay_min, delay_max)
        # Print the exact wait time FIRST, then actually sleep
        print(
            f"⏳ 随机等待 {sleep_seconds} 秒 "
            f"({format_duration(sleep_seconds)}) 后发送，现在开始睡眠..."
        )
        await asyncio.sleep(sleep_seconds)
        now_tz = now_in_timezone(tz_name)
        print("⏳ 睡眠结束，继续执行")
    else:
        print("⏳ --no-delay 或试运行模式，跳过等待")

    # ── Time + period (after wait = actual send time) ───────
    print(f"🕐 真实发送{tz_display_name(tz_name)}时间: {now_tz.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏰ 时间段: {period_cn}")
    print()

    # ── Step 4: Prepare messages (silently, brief output) ───
    special_targets: list[tuple[int, dict, str]] = []
    normal_targets_data: list[dict] = []
    normal_indices: list[int] = []

    for i, target in enumerate(targets):
        tz = target.get("timezone", tz_name)
        target_now = now_in_timezone(tz)
        special_msg = check_special_date(target, target_now, period)
        if special_msg:
            special_targets.append((i, target, special_msg))
            print(f"🎉 {target['name']}: 今日特殊日期，发送专属祝福")
        else:
            period_target = get_period_config(target, period)
            try:
                messages = load_message_pool(period_target, project_root)
            except (FileNotFoundError, ValueError) as e:
                print(f"⚠️  {target['name']}: 加载消息失败: {e}")
                continue
            if not messages:
                print(f"⚠️  {target['name']}: 消息池为空，跳过")
                continue
            normal_targets_data.append({
                "target": target,
                "messages": messages,
                "selection_mode": period_target.get("selection_mode", "random"),
            })
            normal_indices.append(i)

    # Batch-select no-duplicate messages for normal targets
    if normal_targets_data:
        normal_messages = select_messages_batch(normal_targets_data, now_tz)
    else:
        normal_messages = []

    # Assemble final send list
    send_list: list[tuple[dict, str]] = []
    normal_msg_idx = 0
    for i, target in enumerate(targets):
        special_match = next((m for idx, t, m in special_targets if idx == i), None)
        if special_match is not None:
            send_list.append((target, special_match))
        elif i in normal_indices:
            if normal_msg_idx < len(normal_messages):
                send_list.append((target, normal_messages[normal_msg_idx]))
                normal_msg_idx += 1

    if not send_list:
        print("⚠️  没有可发送的消息，退出")
        return 0

    # ── Step 5: Connect and send (with global timeout) ──────
    results: list[dict] = []
    timed_out = False

    if dry_run:
        print("🔍 试运行模式 (不实际发送)")
        for target, msg in send_list:
            print(f"✉️  将发送给 {target['name']} | 内容: {msg}")
            results.append({
                "success": True,
                "target": target.get("chat_id") or target.get("username"),
                "message": msg,
                "dry_run": True,
            })
    else:
        async def do_sending() -> None:
            """Inner coroutine wrapped by global timeout."""
            nonlocal results
            async with TelegramSender(
                api_id=cfg["api_id"],
                api_hash=cfg["api_hash"],
                session_string=cfg["session_string"],
                proxy=cfg.get("proxy"),
            ) as sender:
                print("✅ 成功连接到 Telegram")

                # Get current account name
                try:
                    me = await sender.get_me()
                    account_name = me.first_name or me.username or "Unknown"
                    print(f"👤 当前账号: {account_name}")
                except Exception:
                    print("👤 当前账号: (获取失败)")

                inter_min = cfg.get("inter_target_delay_min", 2)
                inter_max = cfg.get("inter_target_delay_max", 5)
                typing_min = cfg.get("typing_min", 1.5)
                typing_max = cfg.get("typing_max", 4.0)

                for idx, (target, msg) in enumerate(send_list):
                    target_name = target["name"]
                    chat_id = target.get("chat_id") or target.get("username")

                    # Inter-target delay
                    if idx > 0 and not args.no_delay:
                        delay = random.uniform(inter_min, inter_max)
                        print(f"⏳ 等待 {delay:.1f} 秒...")
                        await asyncio.sleep(delay)

                    result = await sender.send_message_human(
                        chat_id,
                        msg,
                        display_name=target_name,
                        typing_min=typing_min,
                        typing_max=typing_max,
                    )
                    results.append(result)
                    if not result["success"]:
                        print(f"❌ 发送失败: {target_name} - {result.get('error')}")

                # Execution report to self
                print()
                print("📋 发送执行报告到自己...")
                await send_execution_report(sender, period, results, now_tz, dry_run)

                # ── Step 6: Set offline and disconnect ───────────
                print()
                print("🟠 正在设置为离线状态...")
                offline_ok = await sender.set_offline()
                if offline_ok:
                    print("✅ 已设置为离线状态")
                else:
                    print("⚠️  设置离线状态失败 (非致命)")
            # async with exits here -> disconnect() is called automatically
            print("✅ 已断开连接")

        try:
            await asyncio.wait_for(do_sending(), timeout=GLOBAL_SEND_TIMEOUT)
        except asyncio.TimeoutError:
            timed_out = True
            print(f"\n⏰ 全局超时 ({GLOBAL_SEND_TIMEOUT}秒)，强制终止发送")
            print(f"   已完成 {len(results)}/{len(send_list)} 条消息")

    # ── Summary ──────────────────────────────────────────────
    success_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - success_count
    print()
    if timed_out:
        print(f"📊 发送超时! 成功: {success_count}, 失败: {fail_count}, 未发送: {len(send_list) - len(results)}")
    else:
        print(f"📊 发送完成! 成功: {success_count}, 失败: {fail_count}")
    print("🏁 脚本执行完毕, 账号已离线")
    return 0 if fail_count == 0 and not timed_out else 1


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        exit_code = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n⏹️  用户中断")
        exit_code = 130
    except Exception as e:
        print(f"\n💥 致命错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
