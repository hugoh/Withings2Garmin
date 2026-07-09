"""Resolve config/data/log file locations.

Defaults follow OS-appropriate conventions via `platformdirs` (XDG on Linux,
native equivalents on macOS/Windows), so an installed `withings2garmin` isn't
tied to whatever directory it happens to be invoked from. Every path is
independently overridable via an env var. Credential/token paths also check
the current working directory first, so local dev (`uv run` from the repo)
and existing installs that always run from the same directory keep working
unchanged.
"""

import os
from pathlib import Path

import platformdirs

APP_NAME = "withings2garmin"


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    override = os.getenv("WITHINGS2GARMIN_CONFIG_DIR")
    return _ensure(
        Path(override) if override else Path(platformdirs.user_config_dir(APP_NAME))
    )


def data_dir() -> Path:
    override = os.getenv("WITHINGS2GARMIN_DATA_DIR")
    return _ensure(
        Path(override) if override else Path(platformdirs.user_data_dir(APP_NAME))
    )


def log_dir() -> Path:
    override = os.getenv("WITHINGS2GARMIN_LOG_DIR")
    return _ensure(
        Path(override) if override else Path(platformdirs.user_log_dir(APP_NAME))
    )


def resolve_env_file() -> Path:
    """$WITHINGS2GARMIN_CONFIG_FILE -> ./.env (cwd, dev) -> config_dir()/config.env."""
    override = os.getenv("WITHINGS2GARMIN_CONFIG_FILE")
    if override:
        return Path(override)
    cwd_env = Path(".env")
    return cwd_env if cwd_env.exists() else config_dir() / "config.env"


def _resolve_data_path(cwd_name: str, env_var: str, default_name: str) -> Path:
    """<env override> -> ./<cwd_name> (dev/existing) -> data_dir()/<default_name>."""
    override = os.getenv(env_var)
    if override:
        return Path(override)
    cwd_path = Path(cwd_name)
    return cwd_path if cwd_path.exists() else data_dir() / default_name


def withings_tokens_file() -> Path:
    return _resolve_data_path(
        ".withings_tokens.json", "WITHINGS_TOKENS_FILE", "withings_tokens.json"
    )


def garmin_session_dir() -> Path:
    return _resolve_data_path(".garmin_session", "GARMIN_SESSION_DIR", "garmin_session")
