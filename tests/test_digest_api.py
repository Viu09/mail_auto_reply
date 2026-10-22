"""GET /api/digest : cle, parametre since, forme de la reponse, codes HTTP et en-tetes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import api as api_module
from app.auth import create_token
from tests.conftest import auth, make_email, make_settings, new_key


JSON_UTF8 = "application/json; charset=utf-8"
NON_CONFIGURE = b'{"code":"digest_non_configure"}'


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _assert_headers(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == JSON_UTF8


# ------------------------------------------------------------------ cle non configuree (503)


@pytest.mark.parametrize("key", ["", "trop-courte", None])
def test_cle_absente_ou_invalide_donne_503_non_configure(install, database, tmp_path, key):
    session_secret = new_key()
    settings = make_settings(
        tmp_path,
        session_secret=session_secret,
        routines_digest_key=session_secret if key is None else key,  # None : egale a SESSION_SECRET
    )
    client = install(settings, database)
    for headers in ({}, auth(settings.routines_digest_key or "x"), auth(new_key())):
        response = client.get("/api/digest", headers=headers)
        assert response.status_code == 503
        assert response.content == NON_CONFIGURE
        _assert_headers(response)


def test_cle_suivante_seule_ne_suffit_pas(install, database, tmp_path):
    suivante = new_key()
    settings = make_settings(tmp_path, routines_digest_key="", routines_digest_key_suivante=suivante)
    response = install(settings, database).get("/api/digest", headers=auth(suivante))
    assert response.status_code == 503
    assert response.content == NON_CONFIGURE


# ------------------------------------------------------------------ cle refusee (401)


def test_refus_sans_entete_ou_avec_mauvaise_cle(client, settings):
    cases = [
        {},
        auth(new_key()),
        auth(settings.routines_digest_key[:-1]),
        {"Authorization": f"Basic {settings.routines_digest_key}"},
        {"Authorization": settings.routines_digest_key},
    ]
    for headers in cases:
        response = client.get("/api/digest", headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {"detail": "Cle de digest invalide."}
        _assert_headers(response)


def test_jeton_de_session_refuse(client, settings):
    token = create_token("samo@example.test", settings)
    response = client.get("/api/digest", headers=auth(token))
    assert response.status_code == 401


def test_cle_en_query_jamais_lue(client, settings):
    response = client.get(f"/api/digest?token={settings.routines_digest_key}")
    assert response.status_code == 401


def test_cle_de_digest_n_ouvre_aucune_autre_route(client, settings):
    assert client.get("/me", headers=auth(settings.routines_digest_key)).status_code == 401


def test_cle_non_ascii_refusee_sans_erreur(client):
    response = client.get("/api/digest", headers={"Authorization": "Bearer clé-éèà-ünïcode".encode("utf-8")})
    assert response.status_code == 401


# ------------------------------------------------------------------ cles acceptees (200) et rotation


def test_cle_principale_et_cle_suivante(install, database, tmp_path):
    principale, suivante = new_key(), new_key()
    settings = make_settings(tmp_path, routines_digest_key=principale, routines_digest_key_suivante=suivante)
    client = install(settings, database)
    assert client.get("/api/digest", headers=auth(principale)).status_code == 200
    assert client.get("/api/digest", headers=auth(suivante)).status_code == 200


def test_cle_suivante_invalide_ignoree(install, database, tmp_path):
    settings = make_settings(tmp_path, routines_digest_key_suivante="courte")
    client = install(settings, database)
    assert client.get("/api/digest", headers=auth("courte")).status_code == 401
    assert client.get("/api/digest", headers=auth(settings.routines_digest_key)).status_code == 200


# ------------------------------------------------------------------ since


def _get(client, settings, since: str | None = None):
    url = "/api/digest" if since is None else f"/api/digest?since={since}"
    return client.get(url, headers=auth(settings.routines_digest_key))


def test_since_absent_vaut_24_h(client, settings):
    body = _get(client, settings).json()
    assert _parse(body["since"]) == _parse(body["generatedAt"]) - timedelta(hours=24)


def test_since_trop_ancien_ramene_a_7_jours(client, settings):
    since = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = _get(client, settings, since).json()
    assert _parse(body["since"]) == _parse(body["generatedAt"]) - timedelta(days=7)


def test_since_legerement_futur_ramene_a_maintenant(client, settings):
    since = (datetime.now(timezone.utc) + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = _get(client, settings, since).json()
    assert body["since"] == body["generatedAt"]


def test_since_avec_decalage_converti_en_utc(client, settings):
    instant = (datetime.now(timezone.utc) - timedelta(hours=5)).replace(microsecond=0)
    local = instant.astimezone(timezone(timedelta(hours=2))).isoformat()
    body = _get(client, settings, quote(local)).json()
    assert body["since"] == instant.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize("since", ["x", "", "2026-10-15", "2026-10-15T19:00:00", "2026-10-15T19:00:00+02:00", "FUTUR"])
def test_since_invalide_donne_400(client, settings, since):
    if since == "FUTUR":
        since = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # « +02:00 » non encode : le + devient une espace, valeur illisible (fiche §8.4).
    response = _get(client, settings, since)
    assert response.status_code == 400
    assert response.json() == {"detail": "Parametre since invalide (ISO 8601 avec Z ou decalage)."}
    _assert_headers(response)


def test_since_hors_limites_donne_400(client, settings):
    assert _get(client, settings, quote("0001-01-01T00:00:00+01:00")).status_code == 400


def test_ordre_des_controles_cle_avant_since(client):
    assert client.get("/api/digest?since=x").status_code == 401


# ------------------------------------------------------------------ forme et en-tetes


def test_forme_de_la_reponse_200(client, settings, database):
    make_email(database, received_at=datetime.now(timezone.utc) - timedelta(hours=1))
    response = _get(client, settings)
    assert response.status_code == 200
    _assert_headers(response)
    body = response.json()
    assert body["version"] == 1
    assert body["tool"] == "mail_auto_reply"
    assert body["timezone"] == "Europe/Brussels"
    assert body["since"] is not None
    assert "effectiveSince" not in body
    assert list(body)[:6] == ["version", "tool", "generatedAt", "since", "timezone", "health"]
    assert body["health"]["status"] in ("ok", "degraded")
    for key in ("metrics", "events", "todos"):
        assert isinstance(body[key], list)
    assert body["health"]["checks"][0] == {"key": "database", "label": "Base de données", "status": "ok"}


def test_route_absente_d_openapi_et_get_seul(client, settings):
    assert "/api/digest" not in client.get("/openapi.json").json()["paths"]
    assert client.post("/api/digest", headers=auth(settings.routines_digest_key)).status_code == 405


def test_base_injoignable_donne_503_minimal(client, settings, database):
    engine = create_engine("sqlite:////dossier-inexistant-routines/t.db")
    database.engine = engine
    database.session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    response = _get(client, settings)
    assert response.status_code == 503
    _assert_headers(response)
    body = response.json()
    assert body["health"] == {
        "status": "down",
        "checks": [{"key": "database", "label": "Base de données", "status": "down",
                    "detail": "Base de données injoignable"}],
    }
    assert body["metrics"] == [] and body["events"] == [] and body["todos"] == []
    assert body["version"] == 1 and body["tool"] == "mail_auto_reply" and body["since"]


def test_exception_hors_section_donne_500_sans_message(client, settings, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("PIEGE-EXCEPTION jean@exemple.be SELECT * FROM processed_emails")

    monkeypatch.setattr(api_module, "build_digest", boom)
    response = _get(client, settings)
    assert response.status_code == 500
    _assert_headers(response)
    assert response.json() == {"detail": "Erreur interne."}
    output = capsys.readouterr().out
    assert "PIEGE-EXCEPTION" not in output and "RuntimeError" in output


def test_journal_sans_donnee_personnelle(client, settings, database, capsys):
    make_email(database, received_at=datetime.now(timezone.utc) - timedelta(hours=1))
    _get(client, settings)
    output = capsys.readouterr().out
    assert "[digest] 200" in output
    assert "Janssens" not in output and "@" not in output and settings.routines_digest_key not in output
