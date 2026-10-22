"""Pieces jointes envoyees a Claude : type reel des images, PDF valides, repli sans piece jointe
sur une 400, et libelle de l'erreur dans le digest. Sans reseau : l'appel a Claude est simule."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app import anthropic_client, worker
from app.anthropic_client import AIClient, is_attachment_rejection
from app.digest import build_digest, error_label, mailbox_alias
from app.models import EmailMessage
from tests.conftest import FIXED_NOW, env_account, set_heartbeat

PNG =b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
GIF87 = b"GIF87a" + b"\x00" * 40
GIF89 = b"GIF89a" + b"\x00" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 40
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40
BMP = b"BM" + b"\x00" * 40
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

# Messages reels des journaux du worker du 2026-10-22.
IMAGE_ERROR = ("messages.0.content.1.image.source.base64: The image was specified using the image/png "
               "media type, but the image appears to be a image/jpeg image")
PDF_ERROR = "messages.0.content.1.pdf.source.base64.data: The PDF specified was not valid."
CREDIT_ERROR = ("Your credit balance is too low to access the Anthropic API. "
                "Please go to Plans & Billing to upgrade or purchase credits.")

ANALYSIS = {
    "target_language": "French", "summary": "Contexte : test", "detailed_summary": "Synthese",
    "category": "Logement", "tags": [], "priority": "medium", "should_reply": True,
    "suggested_reply": "Bonjour", "required_documents": [], "provided_documents": [],
    "attachment_analysis": "Pieces jointes non lues.",
}


def _api_error(status: int, message: str, error_type: str = "invalid_request_error") -> anthropic.APIStatusError:
    """Erreur construite comme le SDK la construit a partir de la reponse HTTP."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    response = httpx.Response(status, request=request, json=body)
    return anthropic.Anthropic(api_key="cle-factice-de-test")._make_status_error(
        f"Error code: {status} - {body}", body=body, response=response)


def _client() -> AIClient:
    return AIClient(api_key="cle-factice-de-test", model="modele-de-test", reply_language="fr")


def _file(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _email() -> EmailMessage:
    return EmailMessage(
        gmail_id="g1", thread_id="t1", subject="Dossier", sender="Sophie <sophie@exemple.be>",
        snippet="", body_text="Voici les pieces.", attachment_names=["scan.png", "bail.pdf"],
        reply_to="sophie@exemple.be", internet_message_id="<m1@exemple.be>", attachments=[],
        account_id="permisrapide-be",
    )


# ------------------------------------------------------------------ images


@pytest.mark.parametrize("data,declared,name,expected", [
    (JPEG, "image/png", "scan.png", "image/jpeg"),  # cas de la boite permisrapide-be
    (PNG, "image/jpeg", "photo.jpg", "image/png"),
    (GIF87, "image/png", "anim.png", "image/gif"),
    (GIF89, "image/jpeg", "anim.jpg", "image/gif"),
    (WEBP, "image/jpeg", "photo.jpg", "image/webp"),
    (JPEG, "application/octet-stream", "scan", "image/jpeg"),
])
def test_image_envoyee_avec_son_type_reel(tmp_path, data, declared, name, expected):
    block = _client()._attachment_to_block(_file(tmp_path, name, data), declared, name)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == expected


@pytest.mark.parametrize("data,declared,name", [
    (HEIC, "image/heic", "photo.heic"),
    (BMP, "image/png", "image.png"),
    (b"<html>erreur</html>", "image/jpeg", "photo.jpg"),
    (b"", "image/png", "vide.png"),
])
def test_image_au_format_non_pris_en_charge_non_envoyee(tmp_path, data, declared, name):
    block = _client()._attachment_to_block(_file(tmp_path, name, data), declared, name)
    assert block["type"] == "text"
    assert name in block["text"] and "non pris en charge" in block["text"]


def test_image_trop_volumineuse(tmp_path, monkeypatch):
    monkeypatch.setattr(anthropic_client, "MAX_IMAGE_BYTES", 10)
    block = _client()._attachment_to_block(_file(tmp_path, "scan.png", JPEG), "image/png", "scan.png")
    assert block["type"] == "text" and "trop volumineuse" in block["text"]


# ------------------------------------------------------------------ PDF


def test_pdf_valide_envoye(tmp_path):
    block = _client()._attachment_to_block(_file(tmp_path, "bail.pdf", PDF), "application/pdf", "bail.pdf")
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf" and block["title"] == "bail.pdf"


@pytest.mark.parametrize("data", [
    b"<!DOCTYPE html><html>Page d'erreur</html>",  # cas de la boite palace-imperial12
    b"PK\x03\x04 archive",
    b"",
])
def test_pdf_invalide_ecarte(tmp_path, data):
    block = _client()._attachment_to_block(_file(tmp_path, "bail.pdf", data), "application/pdf", "bail.pdf")
    assert block["type"] == "text"
    assert "bail.pdf" in block["text"] and "PDF invalide" in block["text"]


def test_pdf_trop_volumineux(tmp_path, monkeypatch):
    monkeypatch.setattr(anthropic_client, "MAX_PDF_BYTES", 10)
    block = _client()._attachment_to_block(_file(tmp_path, "bail.pdf", PDF), "application/pdf", "bail.pdf")
    assert block["type"] == "text" and "trop volumineux" in block["text"]


@pytest.mark.parametrize("declared,name", [("application/octet-stream", "piece"), ("image/png", "scan.png")])
def test_pdf_reconnu_a_ses_octets(tmp_path, declared, name):
    block = _client()._attachment_to_block(_file(tmp_path, name, PDF), declared, name)
    assert block["type"] == "document"


# ------------------------------------------------------------------ repli sans piece jointe


def _fake_claude(client: AIClient, errors: list[Exception]) -> list[list[dict]]:
    """Remplace l'appel HTTP : leve les erreurs donnees dans l'ordre, puis renvoie une analyse."""
    calls: list[list[dict]] = []

    def create(**kwargs):
        calls.append(kwargs["messages"][0]["content"])
        if errors:
            raise errors.pop(0)
        text = SimpleNamespace(type="text", text=json.dumps(ANALYSIS))
        return SimpleNamespace(stop_reason="end_turn", content=[text])

    client.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return calls


def _attachments(tmp_path: Path) -> list[dict]:
    return [
        {"path": _file(tmp_path, "scan.png", JPEG), "mime_type": "image/png", "filename": "scan.png"},
        {"path": _file(tmp_path, "bail.pdf", PDF), "mime_type": "application/pdf", "filename": "bail.pdf"},
    ]


def _types(content: list[dict]) -> list[str]:
    return [block["type"] for block in content]


@pytest.mark.parametrize("message", [IMAGE_ERROR, PDF_ERROR])
def test_repli_sans_piece_jointe_sur_une_400(tmp_path, message, capsys):
    client = _client()
    calls = _fake_claude(client, [_api_error(400, message)])
    analysis = client.analyze_email(_email(), "fr", "Test", attachments=_attachments(tmp_path))
    assert analysis.summary == "Contexte : test"
    assert len(calls) == 2  # une seule nouvelle analyse
    assert _types(calls[0]) == ["text", "image", "document"]
    assert _types(calls[1]) == ["text", "text"]  # aucune image ni aucun document
    assert "scan.png, bail.pdf" in calls[1][1]["text"] and "non lues" in calls[1][1]["text"]
    assert "nouvelle analyse sans piece jointe" in capsys.readouterr().out


def test_repli_unique_si_la_nouvelle_analyse_echoue(tmp_path):
    client = _client()
    calls = _fake_claude(client, [_api_error(400, IMAGE_ERROR), _api_error(529, "Overloaded", "overloaded_error")])
    with pytest.raises(anthropic.APIStatusError) as raised:
        client.analyze_email(_email(), "fr", "Test", attachments=_attachments(tmp_path))
    assert raised.value.status_code == 529 and len(calls) == 2


@pytest.mark.parametrize("status,message,error_type", [
    (429, "Number of request tokens has exceeded your per-minute rate limit", "rate_limit_error"),
    (401, "invalid x-api-key", "authentication_error"),
    (403, "Your API key does not have permission to use the specified resource.", "permission_error"),
    (500, "Internal server error", "api_error"),
    (400, CREDIT_ERROR, "invalid_request_error"),  # facturation : pas une piece jointe
    (400, "messages: text content blocks must be non-empty", "invalid_request_error"),
])
def test_aucun_repli_sur_les_autres_erreurs(tmp_path, status, message, error_type):
    client = _client()
    calls = _fake_claude(client, [_api_error(status, message, error_type)])
    with pytest.raises(anthropic.APIStatusError) as raised:
        client.analyze_email(_email(), "fr", "Test", attachments=_attachments(tmp_path))
    assert raised.value.status_code == status
    assert len(calls) == 1


def test_aucun_repli_sans_piece_jointe_a_retirer():
    client = _client()
    calls = _fake_claude(client, [_api_error(400, IMAGE_ERROR)])
    with pytest.raises(anthropic.BadRequestError):
        client.analyze_email(_email(), "fr", "Test", attachments=[])
    assert len(calls) == 1


def test_detection_d_une_piece_jointe_refusee():
    assert is_attachment_rejection(_api_error(400, IMAGE_ERROR))
    assert is_attachment_rejection(_api_error(400, PDF_ERROR))
    assert is_attachment_rejection(_api_error(400, "messages.0.content.2.document.source: invalid"))
    assert not is_attachment_rejection(_api_error(400, CREDIT_ERROR))
    assert not is_attachment_rejection(_api_error(429, IMAGE_ERROR, "rate_limit_error"))
    assert not is_attachment_rejection(_api_error(400, "prompt is too long"))


# ------------------------------------------------------------------ classement et libelles


@pytest.mark.parametrize("exc,kind", [
    (_api_error(400, IMAGE_ERROR), "claude_attachment"),
    (_api_error(400, PDF_ERROR), "claude_attachment"),
    (_api_error(400, CREDIT_ERROR), "claude_quota"),
    (_api_error(401, "invalid x-api-key", "authentication_error"), "claude_quota"),
    (_api_error(402, "Payment required", "billing_error"), "claude_quota"),
    (_api_error(403, "forbidden", "permission_error"), "claude_quota"),
    (_api_error(429, "rate limit", "rate_limit_error"), "claude_quota"),
    (_api_error(500, "Internal server error", "api_error"), "claude_unavailable"),
    (_api_error(529, "Overloaded", "overloaded_error"), "claude_unavailable"),
    (anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
     "claude_unavailable"),
    (_api_error(404, "model: modele-de-test", "not_found_error"), "claude"),
    (_api_error(400, "prompt is too long"), "claude"),
])
def test_classement_des_erreurs_claude(exc, kind):
    assert worker._error_kind(exc) == kind


@pytest.mark.parametrize("kind,error_class,label", [
    ("claude_attachment", "BadRequestError", "Pièce jointe refusée par Claude (format ou contenu invalide)."),
    ("claude_quota", "RateLimitError", "Erreur Claude (crédit, quota ou clé)."),
    ("claude_unavailable", "OverloadedError", "Claude indisponible ou surchargé (erreur temporaire)."),
    ("claude", "NotFoundError", "Erreur Claude (voir les journaux du worker). Un mail peut bloquer la boîte."),
    ("gmail_auth", "RefreshError", "Accès Gmail refusé : jeton expiré ou révoqué. Reconnecter la boîte."),
    ("gmail_api", "HttpError", "Erreur de l'API Gmail."),
    ("other", "ValueError", "Erreur inattendue (voir les journaux du worker)."),
    (None, None, "Erreur inattendue (voir les journaux du worker)."),
    ("inconnu", None, "Erreur inattendue (voir les journaux du worker)."),
    # Lignes ecrites avant ce correctif : seule la classe permet d'affiner.
    ("claude", "RateLimitError", "Erreur Claude (crédit, quota ou clé)."),
    ("claude", "AuthenticationError", "Erreur Claude (crédit, quota ou clé)."),
    ("claude", "InternalServerError", "Claude indisponible ou surchargé (erreur temporaire)."),
    ("claude", "BadRequestError", "Erreur Claude (voir les journaux du worker). Un mail peut bloquer la boîte."),
    ("claude", None, "Erreur Claude (voir les journaux du worker). Un mail peut bloquer la boîte."),
])
def test_libelle_des_erreurs(kind, error_class, label):
    assert error_label(kind, error_class) == label


def test_piece_jointe_refusee_de_la_trace_au_digest(database, settings):
    def ingest(_account):
        raise _api_error(400, IMAGE_ERROR)

    service = SimpleNamespace(
        ctx=SimpleNamespace(database=database, reload_accounts=lambda: None,
                            all_accounts=lambda: [env_account("default")]),
        ingest_account=ingest,
    )
    worker.run_once(service)
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    checks = {c["key"]: c for c in body["health"]["checks"]}
    detail = checks[f"mailbox:{mailbox_alias('default')}"]["detail"]
    assert detail == "Pièce jointe refusée par Claude (format ou contenu invalide)."
    assert "image/png" not in json.dumps(body)  # jamais le message brut


def test_ancienne_trace_claude_affinee_par_la_classe(database, settings):
    set_heartbeat(database, "default", fail_streak=2, last_error_kind="claude", last_error_class="RateLimitError")
    _, body = build_digest(database, settings, since=FIXED_NOW - timedelta(hours=11), now=FIXED_NOW)
    checks = {c["key"]: c for c in body["health"]["checks"]}
    assert checks[f"mailbox:{mailbox_alias('default')}"]["detail"] == "Erreur Claude (crédit, quota ou clé)."
