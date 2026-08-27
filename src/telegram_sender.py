"""Telegram sender module for TG Daily Greeter.
Wraps Telethon client lifecycle with anti-detection features:
- Realistic device profile (phone model, OS version, app version)
- Typing indicator simulation before sending
- Human-like behavior after connect (fetch dialogs, read state)
- Random delays between actions
- Immediate disconnect after all messages sent
- FloodWait auto-retry (max 2), user fatal errors no-retry
"""
import asyncio
import random
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    AuthKeyError,
    FloodWaitError,
    RPCError,
)

# User-related fatal errors — these should NOT be retried.
# Imported safely because exact class names vary across Telethon versions.
try:
    from telethon.errors import (
        InputUserDeactivatedError,
        PeerIdInvalidError,
        UserDeactivatedBanError,
        UserInvalidError,
    )
    USER_FATAL_ERRORS: tuple = (
        UserInvalidError,
        UserDeactivatedBanError,
        PeerIdInvalidError,
        InputUserDeactivatedError,
    )
except ImportError:
    USER_FATAL_ERRORS = ()

from telethon.sessions import StringSession

# Realistic device profiles to rotate through (prevents static fingerprint)
DEVICE_PROFILES = [
    {
        "device_model": "iPhone 15 Pro",
        "system_version": "iOS 17.5.1",
        "app_version": "10.12.1",
        "lang_code": "ru",
        "system_lang_code": "ru-RU",
    },
    {
        "device_model": "iPhone 14",
        "system_version": "iOS 17.4",
        "app_version": "10.11.0",
        "lang_code": "ru",
        "system_lang_code": "ru-RU",
    },
    {
        "device_model": "Pixel 8 Pro",
        "system_version": "Android 14",
        "app_version": "10.12.0",
        "lang_code": "ru",
        "system_lang_code": "ru-RU",
    },
    {
        "device_model": "Galaxy S24 Ultra",
        "system_version": "Android 14",
        "app_version": "10.11.2",
        "lang_code": "ru",
        "system_lang_code": "ru-RU",
    },
]


class TelegramSender:
    """Manages Telethon client with anti-detection and retry logic."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_string: str,
        proxy: str | None = None,
        device_profile: dict | None = None,
    ):
        """Initialize the sender.

        Args:
            api_id: Telegram API ID.
            api_hash: Telegram API hash.
            session_string: Telethon StringSession string.
            proxy: Optional proxy URL (socks5:// or http://).
            device_profile: Optional device info dict. If None, a random
                realistic profile is chosen.
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string
        self.proxy = proxy
        self.device = device_profile or random.choice(DEVICE_PROFILES)
        self._client: TelegramClient | None = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self) -> None:
        """Create and connect the Telethon client with realistic device info."""
        session = StringSession(self.session_string)
        proxy_config = self._parse_proxy(self.proxy) if self.proxy else None

        self._client = TelegramClient(
            session,
            self.api_id,
            self.api_hash,
            proxy=proxy_config,
            connection_retries=3,
            retry_delay=2,
            device_model=self.device["device_model"],
            system_version=self.device["system_version"],
            app_version=self.device["app_version"],
            lang_code=self.device["lang_code"],
            system_lang_code=self.device["system_lang_code"],
        )

        await self._client.connect()

        if not await self._client.is_user_authorized():
            raise AuthKeyError(
                "Session is not authorized. Please run login.py first "
                "to generate a valid session string."
            )

        # Human-like warmup: fetch own info and recent dialogs.
        # This mimics what the official app does on launch.
        print(f"📱 本次模拟设备: {self.device['device_model']} | 系统: {self.device['system_version']}")
        await self._human_warmup()

    async def _human_warmup(self) -> None:
        """Simulate human-like behavior after connecting.

        Fetches own info and a few dialogs, with small random delays,
        so the connection pattern looks like a real user opening the app.
        """
        if not self._client:
            return
        try:
            print("🔄 执行客户端启动预热...")
            # Fetch self info (every app does this on launch)
            await self._client.get_me()
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # Fetch a small number of recent dialogs (app refreshes chat list)
            async for _ in self._client.iter_dialogs(limit=5):
                pass
            print("📋 已刷新最近聊天列表")
            await asyncio.sleep(random.uniform(0.2, 0.6))
            await asyncio.sleep(random.uniform(0.2, 0.6))
        except Exception as e:
            # Warmup failures should not block sending
            print(f"  [Warmup] Non-critical: {e}")

    async def set_offline(self) -> bool:
        """Set the account status to offline via Telegram API.

        Returns:
            True if successful, False otherwise.
        """
        if not self._client:
            return False
        try:
            from telethon.tl.functions.account import UpdateStatusRequest
            await self._client(UpdateStatusRequest(offline=True))
            return True
        except Exception as e:
            print(f"  [Offline] Non-critical: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect the Telethon client immediately."""
        if self._client:
            # Small delay before disconnect to look natural
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await self._client.disconnect()
            self._client = None

    async def send_message_human(
        self,
        target: str | int,
        message: str,
        display_name: str | None = None,
        max_retries: int = 3,
        typing_min: float = 1.5,
        typing_max: float = 4.0,
        max_flood_wait: int = 2,
    ) -> dict[str, Any]:
        """Send a message with typing indicator simulation (human-like).

        Steps:
        1. Resolve target chat (opens the conversation)
        2. Show 'typing...' indicator for a random duration
        3. Send the message
        4. Small post-send delay

        Error handling:
        - FloodWaitError: wait the required seconds + buffer, retry up to
          max_flood_wait times (default 2).
        - User fatal errors (invalid / blocked / deactivated / peer invalid):
          do NOT retry, return failure immediately.
        - Other RPC/network errors: exponential backoff, up to max_retries.

        Args:
            target: Chat ID (int) or username (str starting with @).
            message: Message text to send.
            display_name: Friendly name for console output (e.g. target's name).
            max_retries: Maximum retry attempts for general errors.
            typing_min: Minimum typing simulation seconds.
            typing_max: Maximum typing simulation seconds.
            max_flood_wait: Maximum FloodWait retries (default 2).

        Returns:
            Result dict with 'success', 'target', 'message', 'error' keys.
        """
        if not self._client:
            raise RuntimeError("Client not connected.")

        last_error = None
        flood_wait_count = 0

        for attempt in range(1, max_retries + 1):
            try:
                # Step 1: Resolve / open the conversation
                entity = await self._client.get_entity(target)
                await asyncio.sleep(random.uniform(0.3, 0.7))

                # Step 2: Simulate typing
                name = display_name or str(target)
                typing_duration = random.uniform(typing_min, typing_max)
                print(f"⌨️  正在模拟输入: {name}")
                async with self._client.action(entity, "typing"):
                    await asyncio.sleep(typing_duration)
                    # Step 3: Send while typing indicator is still active
                    print(f"✉️  正在发送消息给: {name} | 内容: {message}")
                    sent = await self._client.send_message(entity, message)

                # Step 4: Small post-send pause (like reading what you sent)
                await asyncio.sleep(random.uniform(0.3, 0.8))
                print(f"✅ 成功发送给: {name}")

                return {
                    "success": True,
                    "target": target,
                    "message": message,
                    "message_id": sent.id,
                    "attempt": attempt,
                    "typing_seconds": round(typing_duration, 1),
                }

            except FloodWaitError as e:
                flood_wait_count += 1
                if flood_wait_count > max_flood_wait:
                    print(
                        f"    [FloodWait] 已达最大重试次数 ({max_flood_wait}次)，放弃发送"
                    )
                    last_error = f"FloodWait: 需等待{e.seconds}s，已达重试上限"
                    break
                wait_seconds = e.seconds + 5
                print(
                    f"    [FloodWait] 被限流，需等待 {e.seconds}s。"
                    f"等待 {wait_seconds}s 后重试 ({flood_wait_count}/{max_flood_wait})..."
                )
                await asyncio.sleep(wait_seconds)
                last_error = f"FloodWait({e.seconds}s)"
                continue

            except USER_FATAL_ERRORS as e:
                # User invalid / blocked / deactivated / peer invalid — do NOT retry
                error_name = type(e).__name__
                print(f"    [UserError] {error_name}: {e} — 不重试")
                return {
                    "success": False,
                    "target": target,
                    "message": message,
                    "error": f"{error_name}: {e}",
                    "fatal": True,
                }

            except (RPCError, OSError, asyncio.TimeoutError, ValueError) as e:
                last_error = str(e)
                if attempt < max_retries:
                    backoff = 2 ** attempt
                    print(
                        f"    [Retry {attempt}/{max_retries}] 错误: {e}. "
                        f"等待 {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue
                break

        return {
            "success": False,
            "target": target,
            "message": message,
            "error": last_error or "Unknown error",
        }

    async def get_me(self) -> Any:
        """Get the current user entity."""
        if not self._client:
            raise RuntimeError("Client not connected.")
        return await self._client.get_me()

    async def send_to_self(self, message: str) -> dict[str, Any]:
        """Send a message to Saved Messages (self) without typing simulation.

        Self-messages don't need typing simulation — it's your own chat.
        """
        return await self.send_message_human(
            "me", message, typing_min=0.3, typing_max=0.8
        )

    @staticmethod
    def _parse_proxy(proxy_url: str) -> tuple | dict:
        """Parse a proxy URL into Telethon-compatible proxy config."""
        from urllib.parse import urlparse

        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port

        if scheme == "socks5":
            return ("socks5", host, port, True, parsed.username, parsed.password)
        elif scheme in ("http", "https"):
            return ("http", host, port, True, parsed.username, parsed.password)
        else:
            raise ValueError(f"Unsupported proxy scheme: {scheme}")
