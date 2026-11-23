"""Runtime settings, read from environment variables at call time."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"


def data_dir() -> Path:
    return Path(os.environ.get("HOMEDESK_DATA", PACKAGE_DIR.parent / "data"))


def db_path() -> Path:
    return data_dir() / "homedesk.db"


def upload_dir() -> Path:
    return data_dir() / "uploads"


def model() -> str:
    return os.environ.get("HOMEDESK_MODEL", "claude-opus-5-5")


def ai_enabled() -> bool:
    """Claude is used when credentials are present, unless HOMEDESK_AI=off."""
    if os.environ.get("HOMEDESK_AI", "").lower() in ("off", "0", "false", "no"):
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def app_url() -> str:
    return os.environ.get("HOMEDESK_URL", "http://127.0.0.1:8000")
