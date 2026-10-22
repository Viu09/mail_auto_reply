"""Trace du worker (worker_heartbeats, D-036) : ecriture par run_once et lecture par le digest."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import anthropic
import httplib2
import httpx
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from app import digest as digest_module
from app import worker
from app.db import WorkerHeartbeat
from app.digest import build_digest, mailbox_alias
from tests.conftest import FIXED_NOW, env_account, make_oauth_account, set_backfill, set_heartbeat


def _service(database, accounts, ingest):
    ctx = SimpleNamespace(database=database, reload_accounts=lambda: None, all_accounts=lambda: accounts)
    return SimpleNamespace(ctx=ctx, ingest_account=ingest)


def _rows(database) -> dict:
    with database.session() as session:
        return {row.scope: row for row in session.query(WorkerHeartbeat).all()}


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def test_run_once_ecrit_la_trace(database, capsys):
    def ingest(account):
        if account.id == "compte-2":
            raise RefreshError("PIEGE-MESSAGE invalid_grant jean@exemple.be")
        return 3

    service = _service(database, [env_account("compte-1"), env_account("compte-2")], ingest)
    worker.run_once(service)
    rows = _rows(database)
    cycle = rows[worker.CYCLE]
    assert cycle.last_success_at is not None and cycle.fail_streak == 0 and cycle.processed_last == 3
    assert rows["compte-1"].fail_streak == 0 and rows["compte-1"].processed_last == 3
    assert rows["compte-1"].last_success_at is not None
    second = rows["compte-2"]
    assert second.fail_streak == 1 and second.last_error_kind == "gmail_auth"
    assert second.last_error_class == "RefreshError" and second.last_success_at is None

    worker.run_once(service)
    assert _rows(database)["compte-2"].fail_streak == 2
    assert _rows(database)["compte-1"].fail_streak == 0
    # La trace ne garde jamais le message brut.
    for row in _rows(database).values():
        assert "PIEGE" not in (row.last_error_class or "") and "PIEGE" not in (row.last_error_kind or "")


def test_heartbeat_en_echec_n_arrete_pas_le_worker(database, monkeypatch, capsys):
    calls = []

    def ingest(account):
        calls.append(account.id)
        return 0

    def broken(*_args, **_kwargs):
        raise RuntimeError("PIEGE-BASE jean@exemple.be")

    monkeypatch.setattr(database, "record_heartbeat", broken)
    worker.run_once(_service(database, [env_account("a"), env_account("b")], ingest))
    assert calls == ["a", "b"]
    output = capsys.readouterr().out
    assert "Heartbeat impossible (__cycle__): RuntimeError" in output
    assert "PIEGE-BASE" not in output


def test_echec_de_cycle_trace(database):
    service = _service(database, [], lambda _account: 0)
    worker._beat(service, worker.CYCLE, ok=False, exc=RuntimeError("PIEGE"))  # except de main()
    cycle = _rows(database)[worker.CYCLE]
    assert cycle.fail_streak == 1 and cycle.last_error_kind == "other" and cycle.last_error_class == "RuntimeError"


@pytest.mark.parametrize("exc,kind", [
    (RefreshError("invalid_grant"), "gmail_auth"),
    (_http_error(401), "gmail_auth"),
    (_http_error(403), "gmail_auth"),
    (_http_error(500), "gmail_api"),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")), "claude"),
    (RuntimeError("Token du compte 'x' illisible ou vide."), "token_unreadable"),
    (RuntimeError("Jeton Gmail invalide ou absent. Regenere token.json."), "gmail_auth"),
    (ValueError("autre"), "other"),
])
def test_classement_des_erreurs(exc, kind):
    assert worker._error_kind(exc) == kind


# ------------------------------------------------------------------ lecture par le digest


def _checks(body: dict) -> dict:
    return {c["key"]: c for c in body["health"]["checks"]}


def test_worker_silencieux(database, settings):
    set_heartbeat(database, worker.CYCLE, last_seen_at=FIXED_NOW - timedelta(minutes=30),
                  last_success_at=FIXED_NOW - timedelta(minutes=31))
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    check = _checks(body)["worker"]
    assert check["status"] == "degraded" and check["detail"] == "Worker silencieux depuis plus de 20 min"
    assert check["lastSuccessAt"] == (FIXED_NOW - timedelta(minutes=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert body["health"]["status"] == "degraded"


def test_worker_sans_signal(database, settings):
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    check = _checks(body)["worker"]
    assert check == {"key": "worker", "label": "Analyse des mails (worker)", "status": "degraded",
                     "detail": "Aucun signal du worker (pas encore redéployé ?)"}


def test_dernier_cycle_en_erreur(database, settings):
    set_heartbeat(database, worker.CYCLE, last_success_at=FIXED_NOW - timedelta(minutes=5),
                  last_error_at=FIXED_NOW - timedelta(minutes=2), last_error_kind="claude", fail_streak=1)
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    assert _checks(body)["worker"]["detail"] == (
        "Dernier cycle en erreur : Erreur Claude (crédit, quota ou clé). Un mail peut bloquer la boîte.")


def test_boite_a_reconnecter(database, settings):
    set_heartbeat(database, worker.CYCLE, last_success_at=FIXED_NOW - timedelta(minutes=1))
    set_heartbeat(database, "default", fail_streak=3, last_error_kind="gmail_auth",
                  last_success_at=FIXED_NOW - timedelta(hours=37))
    set_backfill(database, "default", False)
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    alias = mailbox_alias("default")
    check = _checks(body)[f"mailbox:{alias}"]
    assert check["status"] == "degraded"  # jamais down dans un 200
    assert check["label"] == "Boîte principale"
    assert check["detail"] == ("Accès Gmail refusé : jeton expiré ou révoqué. Reconnecter la boîte. · "
                               "Rattrapage de l'historique en cours")
    todo = next(t for t in body["todos"] if t["type"] == "mailbox.reconnect")
    assert todo["id"] == f"mailbox:{alias}:reconnect" and todo["priority"] == "high"
    assert "url" not in todo  # compte defini par variables d'environnement
    assert todo["context"] == "Action développeur : régénérer le jeton (variable Railway)"
    assert todo["title"] == "Reconnecter la boîte Gmail principale"
    assert all(c["status"] != "down" for c in body["health"]["checks"])


def test_boite_d_un_autre_proprietaire_ignoree(database, settings):
    make_oauth_account(database, "autre-boite", "Autre", "x@exemple.be", owner="autre@example.test")
    set_heartbeat(database, "autre-boite", fail_streak=5, last_error_kind="gmail_auth")
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    assert f"mailbox:{mailbox_alias('autre-boite')}" not in _checks(body)
    assert not [t for t in body["todos"] if t["type"] == "mailbox.reconnect"]


def test_compte_env_desactive_absent(database, tmp_path):
    from app.db import DisabledAccount
    from tests.conftest import make_settings

    settings = make_settings(tmp_path, accounts=[env_account("default"), env_account("pro", "PRO")])
    with database.session() as session:
        session.add(DisabledAccount(id="pro", owner="samo@example.test"))
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    assert f"mailbox:{mailbox_alias('pro')}" not in _checks(body)
    assert f"mailbox:{mailbox_alias('default')}" in _checks(body)


def test_section_trace_en_echec(database, settings, monkeypatch):
    set_heartbeat(database, worker.CYCLE, last_success_at=FIXED_NOW - timedelta(minutes=1))

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(digest_module, "_load_heartbeats", boom)
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    keys = list(_checks(body))
    assert "worker" not in keys and not [k for k in keys if k.startswith("mailbox:")]
    assert "section:heartbeat" in keys
    assert not [t for t in body["todos"] if t["type"] == "mailbox.reconnect"]


def test_section_boites_en_echec(database, settings, monkeypatch):
    set_heartbeat(database, worker.CYCLE, last_success_at=FIXED_NOW - timedelta(minutes=1))
    set_heartbeat(database, "default", fail_streak=3, last_error_kind="gmail_auth")

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(digest_module, "_load_mailboxes", boom)
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    keys = list(_checks(body))
    assert "worker" in keys and "section:mailboxes" in keys
    assert not [k for k in keys if k.startswith("mailbox:")]
    assert not [t for t in body["todos"] if t["type"] == "mailbox.reconnect"]
