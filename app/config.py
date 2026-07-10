from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


DEFAULT_SIGNATURE = "Samo Ferman"


@dataclass(frozen=True)
class AccountConfig:
    """Configuration d'une adresse Gmail surveillee."""

    id: str
    label: str
    gmail_credentials_path: Path
    gmail_token_path: Path
    gmail_query: str
    reply_language: str
    signature: str


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str
    enable_thinking: bool
    poll_interval_seconds: int
    max_ingest_per_cycle: int
    max_scan_per_cycle: int
    default_reply_language: str
    database_url: str
    data_dir: Path
    dashboard_email: str
    dashboard_password: str
    session_secret: str
    accounts: list[AccountConfig] = field(default_factory=list)


def get_settings() -> Settings:
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY est manquant dans l'environnement.")

    base_dir = Path(__file__).resolve().parent.parent
    data_dir = _resolve_path(base_dir, os.getenv("DATA_DIR", "data"))
    secrets_dir = _resolve_path(base_dir, os.getenv("SECRETS_DIR", str(data_dir / "runtime_secrets")))
    secrets_dir.mkdir(parents=True, exist_ok=True)

    default_reply_language = os.getenv("DEFAULT_REPLY_LANGUAGE", "fr").strip() or "fr"
    default_signature = os.getenv("DEFAULT_SIGNATURE", DEFAULT_SIGNATURE).strip() or DEFAULT_SIGNATURE
    # Par defaut on supervise toute la boite (pas seulement les non lus) : la deduplication
    # se fait en base, donc on n'a plus besoin de marquer les mails comme lus.
    default_query = os.getenv("GMAIL_QUERY", "category:primary").strip()

    accounts = _build_accounts(
        base_dir=base_dir,
        secrets_dir=secrets_dir,
        default_query=default_query,
        default_reply_language=default_reply_language,
        default_signature=default_signature,
    )
    if not accounts:
        raise ValueError(
            "Aucun compte email configure. Renseigne MAIL_ACCOUNTS_JSON / MAIL_ACCOUNTS_BASE64 "
            "ou les variables Gmail par defaut (GMAIL_CREDENTIALS_* et GMAIL_TOKEN_*)."
        )

    return Settings(
        anthropic_api_key=anthropic_api_key,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5",
        enable_thinking=os.getenv("ANTHROPIC_ENABLE_THINKING", "false").strip().lower() == "true",
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
        max_ingest_per_cycle=int(os.getenv("MAX_INGEST_PER_CYCLE", "20")),
        max_scan_per_cycle=int(os.getenv("MAX_SCAN_PER_CYCLE", "3000")),
        default_reply_language=default_reply_language,
        database_url=_resolve_database_url(base_dir, data_dir),
        data_dir=data_dir,
        dashboard_email=os.getenv("DASHBOARD_EMAIL", "").strip().lower(),
        dashboard_password=os.getenv("DASHBOARD_PASSWORD", ""),
        session_secret=os.getenv("SESSION_SECRET", "").strip() or "change-me-in-production",
        accounts=accounts,
    )


def _resolve_database_url(base_dir: Path, data_dir: Path) -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        db_path = _resolve_path(base_dir, os.getenv("DATABASE_PATH", str(data_dir / "app.db")))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"

    # Railway fournit parfois postgres://, non reconnu par SQLAlchemy moderne.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _build_accounts(
    base_dir: Path,
    secrets_dir: Path,
    default_query: str,
    default_reply_language: str,
    default_signature: str,
) -> list[AccountConfig]:
    raw_accounts = _load_accounts_payload()

    if raw_accounts is None:
        legacy = _build_legacy_account(
            base_dir=base_dir,
            secrets_dir=secrets_dir,
            default_query=default_query,
            default_reply_language=default_reply_language,
            default_signature=default_signature,
        )
        return [legacy] if legacy else []

    accounts: list[AccountConfig] = []
    seen_ids: set[str] = set()

    for index, entry in enumerate(raw_accounts):
        account_id = _slugify(str(entry.get("id") or entry.get("label") or f"account{index + 1}"))
        if account_id in seen_ids:
            raise ValueError(f"Identifiant de compte duplique: {account_id}")
        seen_ids.add(account_id)

        account_secrets_dir = secrets_dir / "accounts" / account_id
        account_secrets_dir.mkdir(parents=True, exist_ok=True)

        credentials_path = _resolve_account_secret(
            base_dir=base_dir,
            target_dir=account_secrets_dir,
            filename="credentials.json",
            explicit_path=entry.get("credentials_path"),
            raw_value=entry.get("credentials_json"),
            base64_value=entry.get("credentials_base64"),
            fallback_raw=os.getenv("GMAIL_CREDENTIALS_JSON", "").strip(),
            fallback_base64=os.getenv("GMAIL_CREDENTIALS_BASE64", "").strip(),
            fallback_path=os.getenv("GMAIL_CREDENTIALS_PATH", "").strip(),
        )
        token_path = _resolve_account_secret(
            base_dir=base_dir,
            target_dir=account_secrets_dir,
            filename="token.json",
            explicit_path=entry.get("token_path"),
            raw_value=entry.get("token_json"),
            base64_value=entry.get("token_base64"),
        )

        accounts.append(
            AccountConfig(
                id=account_id,
                label=str(entry.get("label") or account_id),
                gmail_credentials_path=credentials_path,
                gmail_token_path=token_path,
                gmail_query=str(entry.get("gmail_query") or entry.get("query") or default_query).strip(),
                reply_language=str(entry.get("reply_language") or default_reply_language).strip(),
                signature=str(entry.get("signature") or default_signature).strip(),
            )
        )

    return accounts


def _build_legacy_account(
    base_dir: Path,
    secrets_dir: Path,
    default_query: str,
    default_reply_language: str,
    default_signature: str,
) -> AccountConfig | None:
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

    if not gmail_credentials_path.exists():
        return None

    return AccountConfig(
        id="default",
        label=os.getenv("DEFAULT_ACCOUNT_LABEL", "").strip(),
        gmail_credentials_path=gmail_credentials_path,
        gmail_token_path=gmail_token_path,
        gmail_query=default_query,
        reply_language=default_reply_language,
        signature=default_signature,
    )


def _load_accounts_payload() -> list[dict] | None:
    raw_value = os.getenv("MAIL_ACCOUNTS_JSON", "").strip()
    base64_value = os.getenv("MAIL_ACCOUNTS_BASE64", "").strip()

    if not raw_value and base64_value:
        raw_value = base64.b64decode(base64_value.encode("utf-8")).decode("utf-8")

    if not raw_value:
        return None

    payload = json.loads(raw_value)
    if isinstance(payload, dict):
        payload = payload.get("accounts", [])
    if not isinstance(payload, list):
        raise ValueError("MAIL_ACCOUNTS doit etre une liste JSON de comptes.")
    return [entry for entry in payload if isinstance(entry, dict)]


def _resolve_account_secret(
    base_dir: Path,
    target_dir: Path,
    filename: str,
    explicit_path: object | None,
    raw_value: object | None,
    base64_value: object | None,
    fallback_raw: str = "",
    fallback_base64: str = "",
    fallback_path: str = "",
) -> Path:
    if explicit_path:
        return _resolve_path(base_dir, str(explicit_path))

    destination = target_dir / filename

    if raw_value:
        destination.write_text(_stringify_secret(raw_value), encoding="utf-8")
        return destination

    if base64_value:
        destination.write_bytes(base64.b64decode(str(base64_value).encode("utf-8")))
        return destination

    if fallback_path:
        return _resolve_path(base_dir, fallback_path)

    if fallback_raw:
        destination.write_text(fallback_raw, encoding="utf-8")
        return destination

    if fallback_base64:
        destination.write_bytes(base64.b64decode(fallback_base64.encode("utf-8")))
        return destination

    return destination


def _stringify_secret(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "account"


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
