from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is an optional runtime helper
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Email Manager Agent"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/email_manager.db")
    cors_origins: str = os.getenv(
        "CORS_ORIGINS",
        ",".join(
            [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5174",
                "http://localhost:5175",
                "http://127.0.0.1:5175",
            ]
        ),
    )

    storage_dir: Path = Path(os.getenv("STORAGE_DIR", "./data/storage"))
    calendar_path: Path = Path(os.getenv("CALENDAR_PATH", "./data/calendars/internal_calendar.ics"))
    agent_log_dir: Path = Path(os.getenv("AGENT_LOG_DIR", "./data/agent-runs"))

    default_timezone: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Singapore")
    raw_retention_days: int = int(os.getenv("RAW_RETENTION_DAYS", "14"))
    reminder_days_before: int = int(os.getenv("REMINDER_DAYS_BEFORE", "1"))

    netease_imap_host: str = os.getenv("NETEASE_IMAP_HOST", "imap.163.com")
    netease_imap_port: int = int(os.getenv("NETEASE_IMAP_PORT", "993"))
    netease_folder: str = os.getenv("NETEASE_FOLDER", "INBOX")

    dashscope_api_key: str | None = os.getenv("DASHSCOPE_API_KEY")
    qwen_base_url: str = os.getenv(
        "QWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    qwen_classifier_model: str = os.getenv("QWEN_CLASSIFIER_MODEL", "qwen3.5-flash")
    qwen_agent_model: str = os.getenv("QWEN_AGENT_MODEL", "qwen3.5-plus")
    qwen_enabled: bool = _bool_env("QWEN_ENABLED", default=True)


settings = Settings()


def ensure_runtime_dirs() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.calendar_path.parent.mkdir(parents=True, exist_ok=True)
    settings.agent_log_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
