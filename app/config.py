from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    gmail_credentials_path: Path
    gmail_token_path: Path
    database_path: Path
    poll_interval_seconds: int
    gmail_query: str
    default_reply_language: str
    enable_desktop_notifications: bool
    enable_telegram_notifications: bool
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_chat_ids: list[str]


def get_settings() -> Settings:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY est manquant dans l'environnement.")

    base_dir = Path(__file__).resolve().parent.parent
    data_dir = _resolve_path(base_dir, os.getenv("DATA_DIR", "data"))
    secrets_dir = _resolve_path(base_dir, os.getenv("SECRETS_DIR", str(data_dir / "runtime_secrets")))
    secrets_dir.mkdir(parents=True, exist_ok=True)

    gmail_credentials_path = _resolve_path(
        base_dir,
        os.getenv("GMAIL_CREDENTIALS_PATH", str(secrets_dir / "credentials.json")),
    )
    gmail_token_path = _resolve_path(
        base_dir,
        os.getenv("GMAIL_TOKEN_PATH", str(secrets_dir / "token.json")),
    )
    _materialize_secret_file(
        gmail_credentials_path,
        raw_env_name="GMAIL_CREDENTIALS_JSON",
        base64_env_name="GMAIL_CREDENTIALS_BASE64",
    )
    _materialize_secret_file(
        gmail_token_path,
        raw_env_name="GMAIL_TOKEN_JSON",
        base64_env_name="GMAIL_TOKEN_BASE64",
    )

    return Settings(
        openai_api_key=openai_api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
        gmail_credentials_path=gmail_credentials_path,
        gmail_token_path=gmail_token_path,
        database_path=_resolve_path(base_dir, os.getenv("DATABASE_PATH", str(data_dir / "app.db"))),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
        gmail_query=os.getenv("GMAIL_QUERY", "is:unread category:primary").strip(),
        default_reply_language=os.getenv("DEFAULT_REPLY_LANGUAGE", "fr").strip(),
        enable_desktop_notifications=os.getenv("ENABLE_DESKTOP_NOTIFICATIONS", "true").strip().lower() == "true",
        enable_telegram_notifications=os.getenv("ENABLE_TELEGRAM_NOTIFICATIONS", "false").strip().lower() == "true",
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        telegram_chat_ids=_parse_telegram_chat_ids(
            os.getenv("TELEGRAM_CHAT_IDS", "").strip(),
            fallback_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        ),
    )


def _resolve_path(base_dir: Path, configured_path: str) -> Path:
    path = Path(configured_path)
    if path.is_absolute():
        return path
    return base_dir / path


def _materialize_secret_file(
    target_path: Path,
    raw_env_name: str,
    base64_env_name: str,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)

    raw_value = os.getenv(raw_env_name, "").strip()
    if raw_value:
        target_path.write_text(raw_value, encoding="utf-8")
        return

    base64_value = os.getenv(base64_env_name, "").strip()
    if base64_value:
        decoded = base64.b64decode(base64_value.encode("utf-8"))
        target_path.write_bytes(decoded)


def _parse_telegram_chat_ids(raw_value: str, fallback_chat_id: str) -> list[str]:
    if raw_value:
        values = [item.strip() for item in raw_value.split(",") if item.strip()]
        if values:
            return values

    if fallback_chat_id:
        return [fallback_chat_id]

    return []
