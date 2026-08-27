"""Configuration loader for TG Daily Greeter.

Loads and validates config.yml, resolves environment variables for
sensitive credentials (api_id, api_hash, session_string).
"""

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or incomplete."""


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load and validate the YAML configuration file.

    Credentials are read from environment variables if not present
    in the YAML (recommended for GitHub Secrets usage).

    Args:
        config_path: Path to config.yml.

    Returns:
        Validated configuration dictionary.

    Raises:
        ConfigError: If required fields are missing or invalid.
    """
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not isinstance(cfg, dict):
        raise ConfigError("Config file must be a YAML mapping at the top level.")

    # Resolve credentials: YAML value takes precedence, then env vars.
    cfg["api_id"] = _resolve_credential(cfg, "api_id", "TG_API_ID", required=True)
    cfg["api_hash"] = _resolve_credential(cfg, "api_hash", "TG_API_HASH", required=True)
    cfg["session_string"] = _resolve_credential(
        cfg, "session_string", "TG_SESSION_STRING", required=True
    )

    # api_id must be int
    try:
        cfg["api_id"] = int(cfg["api_id"])
    except (TypeError, ValueError):
        raise ConfigError("api_id must be an integer.")

    # Defaults
    cfg.setdefault("timezone", "Europe/Moscow")
    cfg.setdefault("default_jitter_minutes", 5)
    cfg.setdefault("dry_run", False)

    # Anti-detection / human-behavior defaults
    # Probability (0.0-1.0) of skipping the entire day's messages
    cfg.setdefault("skip_probability", 0.2)
    # Send time window (seconds). Script sleeps a random duration before
    # connecting, so actual send time is shortly after the trigger.
    # Morning: 06:00 trigger + 1~5 min sleep = send at ~06:01~06:05
    cfg.setdefault("morning_delay_min", 60)
    cfg.setdefault("morning_delay_max", 300)   # 1~5 minutes
    # Evening: 20:00 trigger + 1~5 min sleep = send at ~20:01~20:05
    cfg.setdefault("evening_delay_min", 60)
    cfg.setdefault("evening_delay_max", 300)   # 1~5 minutes
    # Delay between sending to different targets (seconds)
    cfg.setdefault("inter_target_delay_min", 2)
    cfg.setdefault("inter_target_delay_max", 5)
    # Typing indicator duration range (seconds)
    cfg.setdefault("typing_min", 1.5)
    cfg.setdefault("typing_max", 4.0)

    # Validate skip_probability range
    sp = cfg.get("skip_probability", 0.2)
    if not isinstance(sp, (int, float)) or sp < 0 or sp > 1:
        raise ConfigError("skip_probability must be a number between 0 and 1.")

    # Validate targets
    targets = cfg.get("targets")
    if not targets or not isinstance(targets, list):
        raise ConfigError("'targets' must be a non-empty list.")

    for i, target in enumerate(targets):
        _validate_target(target, i, cfg)

    return cfg


def _resolve_credential(
    cfg: dict, key: str, env_var: str, required: bool = False
) -> str | None:
    """Resolve a credential from YAML config or environment variable."""
    value = cfg.get(key)
    if value is None or value == "":
        value = os.environ.get(env_var)
    if required and not value:
        raise ConfigError(
            f"Missing required credential: set '{key}' in config or "
            f"'{env_var}' environment variable."
        )
    return str(value) if value is not None else None


def _validate_target(target: dict, index: int, global_cfg: dict) -> None:
    """Validate a single target entry."""
    if not isinstance(target, dict):
        raise ConfigError(f"targets[{index}] must be a mapping.")

    # Required: name + (chat_id or username)
    if not target.get("name"):
        raise ConfigError(f"targets[{index}].name is required.")

    chat_id = target.get("chat_id")
    username = target.get("username")
    if not chat_id and not username:
        raise ConfigError(
            f"targets[{index}] must have either 'chat_id' or 'username'."
        )

    # Normalize chat_id to int if it looks like one
    if chat_id is not None and isinstance(chat_id, str) and chat_id.lstrip("-").isdigit():
        target["chat_id"] = int(chat_id)

    # Timezone: per-target overrides global
    target.setdefault("timezone", global_cfg.get("timezone", "Europe/Moscow"))

    # Jitter
    target.setdefault("jitter_minutes", global_cfg.get("default_jitter_minutes", 5))

    # Message pool: can be inline list, a file reference, OR
    # period-specific configs (morning.message_file / evening.message_file).
    # At least one message source must exist somewhere.
    msg_pool = target.get("message_pool")
    msg_file = target.get("message_file")

    # Validate period-specific sub-configs if present
    for period in ("morning", "evening"):
        period_cfg = target.get(period)
        if period_cfg is not None:
            if not isinstance(period_cfg, dict):
                raise ConfigError(
                    f"targets[{index}].{period} must be a mapping "
                    f"(with 'message_pool' or 'message_file')."
                )

    # Check if any message source exists (top-level or period-specific)
    has_top_msg = bool(msg_pool or msg_file)
    has_morning_msg = bool(
        isinstance(target.get("morning"), dict)
        and (target["morning"].get("message_pool") or target["morning"].get("message_file"))
    )
    has_evening_msg = bool(
        isinstance(target.get("evening"), dict)
        and (target["evening"].get("message_pool") or target["evening"].get("message_file"))
    )

    if not has_top_msg and not has_morning_msg and not has_evening_msg:
        raise ConfigError(
            f"targets[{index}] must have a message source: "
            f"'message_pool'/'message_file' at top level, OR "
            f"'morning.message_file'/'evening.message_file' sub-configs."
        )

    # Special dates: optional
    target.setdefault("special_dates", {})
