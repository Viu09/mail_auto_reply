"""Contenu du digest : selection, ids stables, tri et plafonds, minimisation, sante partielle."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest

from app import digest as digest_module
from app.digest import _as_utc, _redact, _summary_lines, build_digest, mailbox_alias, sender_name
from tests.conftest import (
    FIXED_NOW,
    OTHER_OWNER,
    TRAP_BODY,
    TRAP_DETAILED,
    TRAP_REPLY,
    TRAP_SNIPPET,
    make_document,
    make_email,
    make_oauth_account,
    make_reply,
    make_settings,
    set_heartbeat,
)


SINCE = datetime(2026, 10, 15, 18, 42, 30, tzinfo=timezone.utc)


def run(database, settings, since: datetime = SINCE, now: datetime = FIXED_NOW) -> dict:
    status, body = build_digest(database, settings, since=since, now=now)
    assert status == 200
    json.dumps(body)  # serialisable
    return body


def metric(body: dict, key: str) -> dict:
    return next(m for m in body["metrics"] if m["key"] == key)


def by_type(items: list[dict], kind: str) -> list[dict]:
    return [item for item in items if item["type"] == kind]


def strings(value: Any, key: str | None = None) -> Iterator[tuple[str | None, str]]:
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item, key)
    elif isinstance(value, dict):
        for k, item in value.items():
            yield from strings(item, k)


def parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ selection


def test_isolation_par_proprietaire(database, settings):
    make_email(database, owner=OTHER_OWNER, tags=["MiseEnDemeure"], subject="PIEGE-AUTRE-PROPRIETAIRE",
               received_at=SINCE + timedelta(hours=1))
    make_document(database, owner=OTHER_OWNER, file_name="PIEGE-AUTRE-DOC.pdf", received_at=SINCE + timedelta(hours=1))
    make_reply(database, SINCE + timedelta(hours=1), owner=OTHER_OWNER)
    body = run(database, settings)
    assert "PIEGE-AUTRE" not in json.dumps(body)
    assert metric(body, "urgent_pending")["value"] == 0
    assert metric(body, "replies_sent_since")["value"] == 0
    assert body["events"] == [] and body["todos"] == []


def test_historique_rattrape_absent(database, settings):
    make_email(database, tags=["MiseEnDemeure"], priority="high",
               received_at=FIXED_NOW - timedelta(days=730), created_at=FIXED_NOW - timedelta(minutes=5))
    make_email(database, priority="high",
               received_at=FIXED_NOW - timedelta(days=20), created_at=FIXED_NOW - timedelta(minutes=5))
    body = run(database, settings)
    assert body["events"] == [] and body["todos"] == []
    assert metric(body, "received_since")["value"] == 0


def test_mail_ingere_en_retard_present_avec_mention(database, settings):
    received = SINCE - timedelta(hours=4, minutes=30)
    created = SINCE + timedelta(minutes=30)
    email_id = make_email(database, priority="high", received_at=received, created_at=created)
    body = run(database, settings)
    event = next(e for e in body["events"] if e["id"] == f"email:{email_id}")
    assert event["type"] == "mail.priority"
    assert parse(event["at"]) == created.replace(microsecond=0)
    assert event["detail"].startswith("Relevé avec 5 h de retard · ")
    assert metric(body, "received_since")["value"] == 1


def test_tous_les_at_posterieurs_a_since(database, settings):
    make_email(database, priority="high", received_at=SINCE + timedelta(seconds=1))
    make_email(database, tags=["Impaye"], received_at=SINCE - timedelta(hours=10), created_at=SINCE + timedelta(seconds=5))
    make_document(database, received_at=SINCE - timedelta(hours=2), created_at=SINCE + timedelta(minutes=1))
    make_email(database, priority="high", received_at=SINCE - timedelta(minutes=1), created_at=SINCE - timedelta(seconds=1))
    body = run(database, settings)
    assert len(body["events"]) == 3
    assert all(parse(e["at"]) >= parse(body["since"]) for e in body["events"])


def test_mise_en_demeure_sans_reponse_attendue(database, settings):
    received = SINCE + timedelta(hours=1)
    email_id = make_email(database, tags=["MiseEnDemeure", "Impaye"], should_reply=False, received_at=received,
                          sender="Étude Claes & Associés <etude@claes.be>", thread_id="18f2b9c8d7e6f5a4")
    body = run(database, settings)
    event = by_type(body["events"], "mail.legal_alert")[0]
    assert event["id"] == f"email:{email_id}" and event["severity"] == "urgent"
    assert event["title"].startswith("Mise en demeure : Étude Claes & Associés — ")
    assert event["tags"] == ["MiseEnDemeure", "Impaye"]
    todo = by_type(body["todos"], "mail.legal_pending")[0]
    assert todo["id"] == "thread:18f2b9c8d7e6f5a4" and todo["priority"] == "high"
    assert parse(todo["dueAt"]) == (received + timedelta(hours=48)).replace(microsecond=0)
    assert "overdueDays" not in todo
    assert todo["title"].startswith("Traiter : Mise en demeure · Étude Claes & Associés — ")
    assert metric(body, "urgent_pending")["value"] == 1


@pytest.mark.parametrize("status,prefix", [("rejected", "Refusé · "), ("sent", "Déjà répondu · ")])
def test_mail_juridique_traite_reste_en_evenement(database, settings, status, prefix):
    make_email(database, tags=["Contentieux"], approval_status=status, received_at=SINCE + timedelta(hours=1))
    body = run(database, settings)
    event = by_type(body["events"], "mail.legal_alert")[0]
    assert event["detail"].startswith(prefix)
    assert body["todos"] == []
    assert metric(body, "urgent_pending")["value"] == 0


def test_filet_de_securite_sur_l_objet(database, settings):
    make_email(database, subject="Dernier rappel avant HUISSIER", tags=[], should_reply=False,
               received_at=SINCE + timedelta(hours=1))
    body = run(database, settings)
    assert by_type(body["events"], "mail.legal_alert")[0]["title"].startswith("Juridique ou financier : ")
    assert by_type(body["todos"], "mail.legal_pending")


def test_un_seul_a_faire_par_fil(database, settings):
    thread = "18f1c0a2b3d4e5f6"
    for hours in (30, 20, 2):
        make_email(database, thread_id=thread, tags=["Impaye"], subject="Rappel charges",
                   sender="Syndic Verhaegen <syndic@verhaegen.be>", received_at=FIXED_NOW - timedelta(hours=hours))
    body = run(database, settings)
    todos = [t for t in body["todos"] if t["id"] == f"thread:{thread}"]
    assert len(todos) == 1 and len(body["todos"]) == 1
    assert parse(todos[0]["dueAt"]) == FIXED_NOW - timedelta(hours=2) + timedelta(hours=48)  # mail le plus recent
    assert metric(body, "urgent_pending")["value"] == 1
    assert len(body["events"]) == 1  # un seul evenement par fil


def test_transition_t3_vers_t2_garde_le_meme_id(database, settings):
    make_email(database, thread_id="18f1d2e3a4b5c6d7", priority="high", received_at=FIXED_NOW - timedelta(hours=2))
    first = run(database, settings)["todos"]
    later = run(database, settings, since=FIXED_NOW + timedelta(days=2), now=FIXED_NOW + timedelta(days=3))["todos"]
    assert [t["type"] for t in first] == ["mail.reply_priority"]
    assert [t["type"] for t in later] == ["mail.reply_overdue"]
    assert first[0]["id"] == later[0]["id"] == "thread:18f1d2e3a4b5c6d7"
    assert later[0]["priority"] == "high" and later[0]["overdueDays"] == 1


def test_relance_dans_le_fil_garde_le_meme_id(database, settings):
    thread = "18f1e4f5a6b7c8d9"
    make_email(database, thread_id=thread, received_at=FIXED_NOW - timedelta(days=3))
    before = run(database, settings)["todos"]
    make_email(database, thread_id=thread, priority="high", subject="Relance", received_at=FIXED_NOW - timedelta(hours=1))
    after = run(database, settings)["todos"]
    assert before[0]["id"] == after[0]["id"] == f"thread:{thread}"
    assert before[0]["type"] == "mail.reply_overdue" and after[0]["type"] == "mail.reply_priority"
    assert parse(after[0]["dueAt"]) == FIXED_NOW - timedelta(hours=1) + timedelta(hours=48)


def test_mail_sans_fil_identifie_par_son_id(database, settings):
    email_id = make_email(database, thread_id="", priority="high", received_at=FIXED_NOW - timedelta(hours=1))
    assert run(database, settings)["todos"][0]["id"] == f"email:{email_id}"


def test_indicateurs(database, settings):
    make_email(database, tags=["MiseEnDemeure"], received_at=FIXED_NOW - timedelta(days=20))  # urgent seulement
    make_email(database, priority="high", received_at=FIXED_NOW - timedelta(days=6, hours=1))  # en retard, prioritaire
    make_email(database, received_at=FIXED_NOW - timedelta(days=3))  # en retard
    make_email(database, received_at=FIXED_NOW - timedelta(hours=3))  # a traiter
    make_email(database, should_reply=False, received_at=FIXED_NOW - timedelta(hours=3))  # publicite : exclue
    make_email(database, approval_status="sent", received_at=SINCE + timedelta(hours=2))  # deja repondu, mais recu
    make_email(database, received_at=FIXED_NOW - timedelta(days=16))  # hors W14
    make_reply(database, SINCE + timedelta(minutes=5))
    make_reply(database, SINCE - timedelta(minutes=5))
    body = run(database, settings)
    values = {m["key"]: m["value"] for m in body["metrics"]}
    assert values == {
        "urgent_pending": 1,
        "overdue_replies": 2,
        "oldest_overdue_days": 6,
        "high_priority_pending": 1,
        "actionable_pending": 3,
        "received_since": 2,
        "replies_sent_since": 1,
    }
    windows = {m["key"]: m.get("window") for m in body["metrics"]}
    assert windows.pop("received_since") == "since" and windows.pop("replies_sent_since") == "since"
    assert all(value is None for value in windows.values())
    for m in body["metrics"]:
        assert set(m) <= {"key", "label", "value", "unit", "window", "hint"}
        assert m["unit"] in ("count", "days")


def test_tags_dans_le_vocabulaire_ferme(database, settings):
    make_email(database, tags=["Visite", "Inconnu", "Vente", "Facture", 42], priority="high",
               received_at=SINCE + timedelta(hours=1))
    make_document(database, category="Facture", file_name="facture_2026.pdf", received_at=SINCE + timedelta(hours=1))
    body = run(database, settings)
    assert by_type(body["events"], "mail.priority")[0]["tags"] == ["Visite", "Vente"]
    assert body["todos"][0]["tags"] == ["Visite", "Vente"]
    assert by_type(body["events"], "document.received")[0]["tags"] == ["Facture"]
    for item in body["events"] + body["todos"]:
        assert set(item.get("tags", [])) <= digest_module.TAG_VOCABULARY


def test_liens_relatifs(database, settings):
    make_email(database, tags=["Sinistre"], received_at=SINCE + timedelta(hours=1))
    make_email(database, required_documents=["certificat PEB"], received_at=SINCE + timedelta(hours=2))
    make_document(database, received_at=SINCE + timedelta(hours=1))
    body = run(database, settings)
    urls = [item["url"] for item in body["events"] + body["todos"] if "url" in item]
    assert urls and all(url.startswith("/") and not url.startswith("//") for url in urls)


def test_documents_demandes_e3_et_t4(database, settings):
    make_email(database, required_documents=["certificat PEB", "attestation du sol"], tags=["Bail", "DocumentManquant"],
               thread_id="18f2b1a0c9d8e7f6", received_at=SINCE + timedelta(hours=3))
    body = run(database, settings)
    event = by_type(body["events"], "mail.documents_requested")[0]
    assert event["title"] == "Documents demandés : Sophie J. — Candidature appartement Ixelles"
    assert event["detail"].startswith("Documents demandés : certificat PEB, attestation du sol · Demande : ")
    todo = by_type(body["todos"], "mail.documents_to_send")[0]
    assert todo["title"] == "Envoyer les documents demandés à Sophie J. — Candidature appartement Ixelles"
    assert todo["context"] == ("Tags : Bail, Document manquant · Documents demandés : certificat PEB, "
                               "attestation du sol · Boîte principale")


def test_document_de_mail_deja_annonce_non_repete(database, settings):
    email_id = make_email(database, priority="high", received_at=SINCE + timedelta(hours=1))
    make_document(database, email_id=email_id, received_at=SINCE + timedelta(hours=1))
    body = run(database, settings)
    assert by_type(body["events"], "document.received") == []
    make_document(database, received_at=SINCE + timedelta(hours=1), sender="Toitures Peeters SRL <t@peeters.be>")
    event = by_type(run(database, settings)["events"], "document.received")[0]
    assert event["title"] == "Devis reçu : Toitures Peeters SRL — devis_toiture_2026-118.pdf"
    assert event["detail"] == "Pièce classée « Devis » dans les documents"
    assert event["severity"] == "info" and event["url"] == "/documents"


# ------------------------------------------------------------------ tri, plafonds, truncated


def test_plafond_des_evenements_et_a_faire(database, settings):
    for index in range(30):
        make_email(database, priority="high", received_at=SINCE + timedelta(minutes=10 + index))
    body = run(database, settings)
    assert len(body["events"]) == 20 and len(body["todos"]) == 15
    assert body["truncated"] == {"events": 10, "todos": 15}
    ats = [e["at"] for e in body["events"]]
    assert ats == sorted(ats, reverse=True)


def test_sous_plafond_des_documents(database, settings):
    for index in range(8):
        make_document(database, file_name=f"contrat_{index}.pdf", category="Contrat",
                      received_at=SINCE + timedelta(minutes=index + 1))
    body = run(database, settings)
    assert len(by_type(body["events"], "document.received")) == 5
    assert body["truncated"] == {"events": 3}


def test_sans_coupe_pas_de_truncated(database, settings):
    make_email(database, priority="high", received_at=SINCE + timedelta(hours=1))
    assert "truncated" not in run(database, settings)


def test_ordre_des_evenements(database, settings):
    make_document(database, received_at=FIXED_NOW - timedelta(minutes=1))
    make_email(database, priority="high", received_at=FIXED_NOW - timedelta(hours=3))
    make_email(database, required_documents=["piece"], received_at=FIXED_NOW - timedelta(hours=1))
    make_email(database, tags=["Procedure"], received_at=FIXED_NOW - timedelta(hours=5))
    body = run(database, settings)
    assert [e["type"] for e in body["events"]] == [
        "mail.legal_alert", "mail.documents_requested", "mail.priority", "document.received",
    ]


def test_ordre_des_a_faire(database, settings):
    settings_oauth = settings
    make_oauth_account(database, "agence-oauth", "Agence", "agence@exemple.be")
    set_heartbeat(database, "agence-oauth", fail_streak=3, last_error_kind="gmail_auth",
                  last_success_at=FIXED_NOW - timedelta(hours=37))
    make_email(database, tags=["Impaye"], received_at=FIXED_NOW - timedelta(days=6))  # T1, retard 4
    make_email(database, priority="high", received_at=FIXED_NOW - timedelta(days=4))  # T2 high, retard 2
    make_email(database, tags=["MiseEnDemeure"], received_at=FIXED_NOW - timedelta(hours=1))  # T1, a echoir
    make_email(database, received_at=FIXED_NOW - timedelta(days=2, hours=5))  # T2 normal, retard 0
    make_email(database, priority="high", received_at=FIXED_NOW - timedelta(hours=14))  # T3
    make_email(database, required_documents=["PEB"], received_at=FIXED_NOW - timedelta(hours=1))  # T4
    make_email(database, summary="Analyse indisponible (reponse du modele non exploitable).", should_reply=False,
               received_at=FIXED_NOW - timedelta(days=1))  # T6
    make_email(database, summary="Analyse indisponible (reponse du modele non exploitable).", should_reply=False,
               received_at=FIXED_NOW - timedelta(days=2))  # T6
    body = run(database, settings_oauth)
    assert [(t["type"], t["priority"], t.get("overdueDays")) for t in body["todos"]] == [
        ("mail.legal_pending", "high", 4),
        ("mail.reply_overdue", "high", 2),
        ("mail.legal_pending", "high", None),
        ("mailbox.reconnect", "high", None),
        ("mail.reply_overdue", "normal", 0),
        ("mail.reply_priority", "normal", None),
        ("mail.documents_to_send", "normal", None),
        ("mail.analysis_failed", "low", None),
    ]
    reconnect = by_type(body["todos"], "mailbox.reconnect")[0]
    assert reconnect["url"] == "/settings" and reconnect["title"] == "Reconnecter la boîte Gmail « Agence »"
    failed = by_type(body["todos"], "mail.analysis_failed")[0]
    assert failed["id"] == "inbox:analysis_failed" and failed["title"] == "2 mails à lire sans résumé IA"
    for todo in body["todos"]:
        assert todo.get("overdueDays", 0) >= 0


# ------------------------------------------------------------------ minimisation


_TEST_PATTERNS = {
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"),
    "telephone": re.compile(r"\+32|0032|\b04\d{2}[ ./]?\d{2}"),
    "iban": re.compile(r"\bBE\d{2}"),
    "url": re.compile(r"https?://|www\.", re.IGNORECASE),
}


def _seed_traps(database) -> None:
    make_oauth_account(database, "samo-d-gmail-com", "samo.d@gmail.com", "samo.d@gmail.com")
    set_heartbeat(database, "samo-d-gmail-com", fail_streak=1, last_error_kind="gmail_api")
    common = dict(
        sender="Sophie Janssens <sophie.janssens@exemple.be>",
        subject="Janssens : écrire à jean.dupont@exemple.be ou au 0470 12 34 56 (https://exemple.be/x)",
        summary=("Contexte : PIEGE-CONTEXTE\n"
                 "Demande : Sophie JANSSENS demande d'appeler le +32 2 123 45 67 ou le 0032 470 12 34 56 "
                 "avant le 02/11/2026 18:00\n"
                 "Point bloquant : PIEGE-BLOCAGE\n"
                 "Action : virer 3 412,50 € sur BE68 5390 0754 7034 (voir www.banque.be)"),
        required_documents=["attestation à envoyer à compta@exemple.be", "relevé BE68539007547034"],
        tags=["Bail", "DocumentManquant"],
    )
    make_email(database, account_id="samo-d-gmail-com", priority="high", received_at=SINCE + timedelta(hours=1), **common)
    make_email(database, account_id="samo-d-gmail-com", received_at=FIXED_NOW - timedelta(days=3), **common)
    make_email(database, account_id="samo-d-gmail-com", tags=["MiseEnDemeure"], received_at=SINCE + timedelta(hours=2),
               **{k: v for k, v in common.items() if k != "tags"})
    make_document(database, account_id="samo-d-gmail-com", file_name="facture Janssens 0470.12.34.56 sophie@x.be.pdf",
                  category="Facture", sender=common["sender"], received_at=SINCE + timedelta(hours=1))


def test_minimisation_marqueurs_pieges(database, settings):
    _seed_traps(database)
    body = run(database, settings)
    serialized = json.dumps(body, ensure_ascii=False)
    assert body["events"] and body["todos"]
    for trap in (TRAP_BODY, TRAP_REPLY, TRAP_SNIPPET, TRAP_DETAILED, "PIEGE-CORPS", "PIEGE-REPONSE", "PIEGE-EXTRAIT",
                 "PIEGE-SYNTHESE", "PIEGE-JETON", "PIEGE-CHEMIN", "PIEGE-RESUME-DOC", "PIEGE-CONTEXTE",
                 "PIEGE-BLOCAGE", "prix plancher", "245000"):
        assert trap not in serialized
    for name, pattern in _TEST_PATTERNS.items():
        assert pattern.search(serialized) is None, name
    # Meme controle que la sonde de minimisation du hub, sur chaque champ texte sauf url.
    for key, value in strings(body):
        if key == "url":
            continue
        for pattern in (digest_module._EMAIL, digest_module._URL, digest_module._IBAN, digest_module._PHONE):
            assert pattern.search(value) is None, (key, pattern.pattern)
    assert "02/11/2026 18:00" in serialized  # une date n'est pas un telephone
    assert "3 412,50 €" in serialized  # les montants restent (resume actionnable)
    assert "Janssens" not in serialized and "JANSSENS" not in serialized
    assert "Sophie J." in serialized


def test_compte_oauth_derive_d_une_adresse_jamais_expose(database, settings):
    _seed_traps(database)
    body = run(database, settings)
    serialized = json.dumps(body, ensure_ascii=False).lower()
    assert "samo-d-gmail-com" not in serialized and "samo.d" not in serialized and "samo" not in serialized
    keys = [c["key"] for c in body["health"]["checks"]]
    assert f"mailbox:{mailbox_alias('samo-d-gmail-com')}" in keys
    label = next(c["label"] for c in body["health"]["checks"] if c["key"].endswith(mailbox_alias("samo-d-gmail-com")))
    assert label == "Boîte n°2"
    for key in keys:
        assert re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key)
    for item in body["events"] + body["todos"]:
        assert re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item["id"])


def test_plafonds_de_texte(database, tmp_path):
    long_label = "Agence " + "x" * 300
    settings = make_settings(tmp_path)
    make_oauth_account(database, "agence", long_label, "a@exemple.be")
    set_heartbeat(database, "agence", fail_streak=4, last_error_kind="gmail_auth")
    long_text = " ".join(["mot"] * 400)
    make_email(database, account_id="agence", subject=long_text, summary=f"Demande : {long_text}\nAction : {long_text}",
               required_documents=[long_text] * 5, tags=["Impaye", "Loyers", "Visite", "Vente", "Bail", "Devis"],
               priority="high", received_at=SINCE + timedelta(hours=1))
    make_email(database, account_id="agence", subject=long_text, priority="high", required_documents=[long_text],
               received_at=FIXED_NOW - timedelta(days=3))
    body = run(database, settings)
    limits = {"title": 140, "detail": 300, "context": 200, "label": 80, "hint": 160}
    seen = set()
    for key, value in strings(body):
        if key in limits:
            seen.add(key)
            assert len(value) <= limits[key], (key, len(value))
    assert seen == set(limits)
    assert any(e["title"].endswith("…") for e in body["events"])


@pytest.mark.parametrize("sender,expected", [
    ("Sophie Janssens <s@exemple.be>", "Sophie J."),
    ("JANSSENS Sophie <s@exemple.be>", "Sophie J."),
    ("sophie janssens <s@exemple.be>", "Sophie J."),
    ("Mme Claire Renard <c@exemple.be>", "Claire R."),
    ("Jean-Marc Van der Berg <j@exemple.be>", "Jean-Marc V."),
    ("Maître Dumont <m@exemple.be>", "Maître D."),
    ("Étude Claes & Associés <e@exemple.be>", "Étude Claes & Associés"),
    ("Toitures Peeters SRL <t@exemple.be>", "Toitures Peeters SRL"),
    ("Syndic Verhaegen <s@exemple.be>", "Syndic Verhaegen"),
    ("<noreply@notaire-dumont.be>", "notaire-dumont"),
    ('"jean@gmail.com" <jean@gmail.com>', "Expéditeur sans nom"),
    ("JEAN SMITH <j@exemple.be>", "J. S."),
    ('"Renard, Claire" <c@exemple.be>', "Claire R."),
    ("Bureau Wouters <b@exemple.be>", "Bureau Wouters"),
    ("Claire <c@exemple.be>", "Claire"),
    ("(expéditeur inconnu)", "Expéditeur sans nom"),
    ("Agence 0470 12 34 56 <a@exemple.be>", "Agence [tél.]"),
])
def test_regle_prenom_initiale(sender, expected):
    assert sender_name(sender).display == expected


def test_nom_de_l_expediteur_remplace_dans_objet_et_resume(database, settings):
    make_email(database, sender="Claire Renard <c@exemple.be>", priority="high", subject="Dossier Renard",
               summary="Demande : Mme RENARD et Claire Renard attendent\nAction : rappeler Renard Claire.",
               received_at=SINCE + timedelta(hours=1))
    event = run(database, settings)["events"][0]
    assert event["title"] == "Mail prioritaire : Claire R. — Dossier Claire R."
    assert "Renard" not in event["detail"] and "RENARD" not in event["detail"]
    assert event["detail"].endswith("Action : rappeler Claire R.")


# ------------------------------------------------------------------ sante partielle


def test_section_documents_en_echec(database, settings, monkeypatch, capsys):
    make_email(database, priority="high", received_at=SINCE + timedelta(hours=1))
    make_document(database, received_at=SINCE + timedelta(hours=1))

    def boom(*_args, **_kwargs):
        raise RuntimeError("PIEGE-MESSAGE-SQL jean@exemple.be")

    monkeypatch.setattr(digest_module, "_load_documents", boom)
    body = run(database, settings)
    check = next(c for c in body["health"]["checks"] if c["key"] == "section:documents")
    assert check == {"key": "section:documents", "label": "Section « Documents » indisponible",
                     "status": "degraded", "detail": "Lecture impossible"}
    assert body["health"]["status"] == "degraded"
    assert by_type(body["events"], "document.received") == []
    assert by_type(body["events"], "mail.priority")
    assert {m["key"] for m in body["metrics"]} >= {"urgent_pending", "replies_sent_since"}
    assert "PIEGE-MESSAGE-SQL" not in json.dumps(body) and "PIEGE-MESSAGE-SQL" not in capsys.readouterr().out
    assert all(c["status"] != "down" for c in body["health"]["checks"])


def test_section_mails_en_echec_n_emet_rien_de_partiel(database, settings, monkeypatch):
    make_email(database, priority="high", received_at=SINCE + timedelta(hours=1))
    make_reply(database, SINCE + timedelta(minutes=1))

    def boom(*_args, **_kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(digest_module, "_legal_label", boom)  # echec au milieu du calcul
    monkeypatch.setattr(digest_module, "_is_legal", lambda *_a: True)
    body = run(database, settings)
    assert [m["key"] for m in body["metrics"]] == ["replies_sent_since"]
    assert body["events"] == [] and body["todos"] == []
    assert any(c["key"] == "section:emails" for c in body["health"]["checks"])


def test_sante_ok_quand_tout_va_bien(database, settings):
    set_heartbeat(database, "__cycle__", last_success_at=FIXED_NOW - timedelta(minutes=1))
    set_heartbeat(database, "default", last_success_at=FIXED_NOW - timedelta(minutes=1))
    body = run(database, settings)
    assert body["health"]["status"] == "ok"
    assert [c["key"] for c in body["health"]["checks"]] == ["database", "worker", f"mailbox:{mailbox_alias('default')}"]


# ------------------------------------------------------------------ outils


def test_dates_naives_traitees_en_utc():
    naive = datetime(2026, 10, 15, 12, 0, 0)
    assert _as_utc(naive) == datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    aware = datetime(2026, 10, 15, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert _as_utc(aware) == datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("text,expected", [
    ("écrire à jean.dupont@exemple.be.", "écrire à [e-mail]."),
    ("voir https://exemple.be/doc?x=1.", "voir [lien]."),
    ("www.exemple.be", "[lien]"),
    ("IBAN BE68 5390 0754 7034 merci", "IBAN [IBAN] merci"),
    ("appeler le 0470 12 34 56", "appeler le [tél.]"),
    ("appeler le 0470/12.34.56", "appeler le [tél.]"),
    ("appeler le +32 470 12 34 56", "appeler le [tél.]"),
    ("appeler le 0032 2 123 45 67", "appeler le [tél.]"),
    ("bureau 02 123 45 67", "bureau [tél.]"),
    ("rendez-vous le 02/11/2026 18:00", "rendez-vous le 02/11/2026 18:00"),
    ("rendez-vous le 02.11.2026 18:00", "rendez-vous le 02.11.2026 18:00"),
    ("prix 3 000 000 € ou 1.050.000 €", "prix 3 000 000 € ou 1.050.000 €"),
    ("a\u200bb\u202ec\nd\te", "abc d e"),
])
def test_caviardage(text, expected):
    assert _redact(text) == expected


def test_lignes_demande_et_action_du_resume():
    summary = "Contexte : x\n- **Demande** : payer\nPoint bloquant : y\nAction recommandée : répondre"
    assert _summary_lines(summary) == "Demande : payer · Action : répondre"
    assert _summary_lines("Newsletter mensuelle de l'agence.\nSans action.") == "Newsletter mensuelle de l'agence."
    assert _summary_lines("") == ""
