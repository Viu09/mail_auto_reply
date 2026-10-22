"""Outils communs des tests du digest Routines (GET /api/digest).

Base SQLite temporaire par test, sans reseau, sans Gmail ni Claude. Les cles de test sont
generees a chaque execution : aucune valeur de secret n'est ecrite dans le depot.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.config import AccountConfig, Settings
from app.db import Account, Database, Document, IngestState, ProcessedEmail, ReplyMemory, WorkerHeartbeat


OWNER = "samo@example.test"
OTHER_OWNER = "autre@example.test"
FIXED_NOW = datetime(2026, 10, 16, 5, 50, 3, tzinfo=timezone.utc)

# Marqueurs pieges : ils ne doivent jamais sortir dans le digest.
TRAP_BODY = "PIEGE-CORPS-7f3a prix plancher 245000 EUR, rappelez le 0470 12 34 56"
TRAP_REPLY = "PIEGE-REPONSE-91bc Bien a vous, iban BE68 5390 0754 7034"
TRAP_SNIPPET = "PIEGE-EXTRAIT-55de"
TRAP_DETAILED = "PIEGE-SYNTHESE-c0ff"


def new_key() -> str:
    return secrets.token_urlsafe(48)  # 64 caracteres, comme 02 §10.1


def env_account(account_id: str = "default", label: str = "") -> AccountConfig:
    return AccountConfig(
        id=account_id,
        label=label,
        gmail_credentials_path=Path("/dev/null"),
        gmail_token_path=Path("/dev/null"),
        gmail_query="category:primary",
        reply_language="fr",
        signature="Test",
    )


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        anthropic_api_key="cle-factice-de-test",
        anthropic_model="modele-de-test",
        enable_thinking=False,
        poll_interval_seconds=60,
        max_ingest_per_cycle=20,
        max_scan_per_cycle=500,
        default_reply_language="fr",
        database_url=f"sqlite:///{tmp_path}/t.db",
        data_dir=tmp_path,
        dashboard_email=OWNER,
        dashboard_password=secrets.token_urlsafe(12),
        primary_owner=OWNER,
        session_secret=new_key(),
        accounts=[env_account()],
        routines_digest_key=new_key(),
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(f"sqlite:///{tmp_path}/t.db", primary_owner=OWNER)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def install():
    """Injecte un contexte (settings, database) dans l'app, sans executer le lifespan."""
    had_context = hasattr(app.state, "context")
    previous = getattr(app.state, "context", None)

    def _install(settings: Settings, database: Database) -> TestClient:
        app.state.context = SimpleNamespace(settings=settings, database=database)
        return TestClient(app)  # hors bloc with : le lifespan exigerait Gmail et Claude

    yield _install
    if had_context:
        app.state.context = previous
    elif hasattr(app.state, "context"):
        del app.state.context


@pytest.fixture
def client(install, settings: Settings, database: Database) -> TestClient:
    return install(settings, database)


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def make_email(database: Database, **fields: Any) -> int:
    received_at = fields.pop("received_at", FIXED_NOW - timedelta(hours=2))
    values: dict[str, Any] = dict(
        owner=OWNER,
        account_id="default",
        gmail_id=uuid.uuid4().hex,
        thread_id=uuid.uuid4().hex[:16],
        sender="Sophie Janssens <sophie.janssens@exemple.be>",
        reply_to="sophie.janssens@exemple.be",
        internet_message_id=f"<{uuid.uuid4().hex}@mail.exemple.be>",
        subject="Candidature appartement Ixelles",
        snippet=TRAP_SNIPPET,
        body_text=TRAP_BODY,
        attachment_analysis="Aucune piece jointe detectee.",
        summary="Contexte : visite faite\nDemande : envoyer le bail\nPoint bloquant : aucun\nAction : repondre avec le bail",
        detailed_summary=TRAP_DETAILED,
        category="Logement",
        tags=[],
        priority="medium",
        suggested_reply=TRAP_REPLY,
        should_reply=True,
        required_documents=[],
        provided_documents=[],
        approval_status="pending",
        received_at=received_at,
        created_at=received_at + timedelta(seconds=40),
    )
    values.update(fields)
    with database.session() as session:
        record = ProcessedEmail(**values)
        session.add(record)
        session.flush()
        return int(record.id)


def make_document(database: Database, **fields: Any) -> int:
    received_at = fields.pop("received_at", FIXED_NOW - timedelta(hours=2))
    values: dict[str, Any] = dict(
        owner=OWNER,
        account_id="default",
        email_id=None,
        gmail_id=uuid.uuid4().hex,
        file_name="devis_toiture_2026-118.pdf",
        local_path="/app/data/PIEGE-CHEMIN/devis.pdf",
        mime_type="application/pdf",
        size_bytes=1000,
        category="Devis",
        summary="PIEGE-RESUME-DOC",
        sender="Toitures Peeters SRL <devis@toitures-peeters.be>",
        subject="Votre devis",
        received_at=received_at,
        created_at=received_at + timedelta(seconds=30),
    )
    values.update(fields)
    with database.session() as session:
        record = Document(**values)
        session.add(record)
        session.flush()
        return int(record.id)


def make_reply(database: Database, created_at: datetime, owner: str = OWNER) -> None:
    with database.session() as session:
        session.add(ReplyMemory(
            owner=owner, account_id="default", category="Logement", tags=[], sender="x",
            subject="x", email_body=TRAP_BODY, final_reply=TRAP_REPLY, created_at=created_at,
        ))


def make_oauth_account(database: Database, account_id: str, label: str, email: str, owner: str = OWNER) -> None:
    with database.session() as session:
        session.add(Account(id=account_id, owner=owner, label=label, email=email, token_json="PIEGE-JETON"))


def set_heartbeat(database: Database, scope: str, **fields: Any) -> None:
    with database.session() as session:
        record = session.get(WorkerHeartbeat, scope) or WorkerHeartbeat(scope=scope)
        record.last_seen_at = fields.pop("last_seen_at", FIXED_NOW - timedelta(minutes=1))
        for key, value in fields.items():
            setattr(record, key, value)
        if record.fail_streak is None:
            record.fail_streak = 0
        if record.processed_last is None:
            record.processed_last = 0
        session.add(record)


def set_backfill(database: Database, account_id: str, done: bool) -> None:
    with database.session() as session:
        session.add(IngestState(account_id=account_id, backfill_done=done))
