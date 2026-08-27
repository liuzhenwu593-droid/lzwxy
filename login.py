#!/usr/bin/env python3
"""TG Daily Greeter - Login helper.

Run this script locally to authenticate your Telegram account and
generate a session string. The session string should then be stored
as a GitHub Secret (TG_SESSION_STRING) for use in GitHub Actions.

Usage:
    python login.py
    python login.py --api-id 12345 --api-hash abcdef...
    python login.py --output session.txt

You will be prompted for your phone number (with country code, e.g. +86...)
and the verification code sent to your Telegram account.
If two-step verification is enabled, you will also be asked for your password.
"""

import argparse
import asyncio
import sys

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Login to Telegram and generate a session string."
    )
    parser.add_argument(
        "--api-id",
        type=int,
        default=None,
        help="Telegram API ID (or set TG_API_ID env var).",
    )
    parser.add_argument(
        "--api-hash",
        default=None,
        help="Telegram API hash (or set TG_API_HASH env var).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write session string to this file as well as printing it.",
    )
    return parser.parse_args()


async def login(api_id: int, api_hash: str, output_file: str | None = None) -> str:
    """Interactive login flow.

    Args:
        api_id: Telegram API ID.
        api_hash: Telegram API hash.
        output_file: Optional path to write the session string.

    Returns:
        The session string.
    """
    session = StringSession()
    client = TelegramClient(session, api_id, api_hash)

    await client.connect()

    if not await client.is_user_authorized():
        phone = input("Enter your phone number (with country code, e.g. +8613800138000): ").strip()
        if not phone:
            raise ValueError("Phone number cannot be empty.")

        print("Sending verification code...")
        await client.send_code_request(phone)

        code = input("Enter the verification code from Telegram: ").strip()
        if not code:
            raise ValueError("Verification code cannot be empty.")

        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = input(
                "Two-step verification is enabled. Enter your password: "
            ).strip()
            await client.sign_in(password=password)

    me = await client.get_me()
    print(f"\nSuccessfully logged in as: {me.first_name} (@{me.username or 'no username'})")
    print(f"User ID: {me.id}")

    session_string = session.save()
    print(f"\n=== YOUR SESSION STRING ===")
    print(session_string)
    print("=== END SESSION STRING ===\n")
    print(
        "IMPORTANT: Store this string as a GitHub Secret named 'TG_SESSION_STRING'.\n"
        "Do NOT commit it to any repository or share it publicly.\n"
        "Anyone with this string can access your Telegram account."
    )

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(session_string)
        print(f"\nSession string also saved to: {output_file}")

    await client.disconnect()
    return session_string


def main() -> None:
    import os

    args = parse_args()

    api_id = args.api_id or int(os.environ.get("TG_API_ID", "0"))
    api_hash = args.api_hash or os.environ.get("TG_API_HASH", "")

    if not api_id or not api_hash:
        print(
            "Error: API ID and API hash are required.\n"
            "Get them from https://my.telegram.org/apps\n"
            "Pass via --api-id / --api-hash or TG_API_ID / TG_API_HASH env vars.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        asyncio.run(login(api_id, api_hash, args.output))
    except KeyboardInterrupt:
        print("\nLogin cancelled.")
        sys.exit(130)
    except Exception as e:
        print(f"\nLogin failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
