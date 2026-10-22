from __future__ import annotations

import time

from app.anthropic_client import is_attachment_rejection, is_billing_error
from app.services import EmailService, build_context


# Ligne de la table worker_heartbeats qui trace le cycle complet (lue par GET /api/digest).
CYCLE = "__cycle__"


def _claude_error_kind(exc: BaseException) -> str:
    """Classe une erreur de l'API Claude d'apres son statut (et son type pour une 400)."""
    status = getattr(exc, "status_code", None)
    if is_attachment_rejection(exc):
        return "claude_attachment"  # 400 sur une image, un PDF ou un document
    if status in (401, 402, 403, 429) or is_billing_error(exc):
        return "claude_quota"  # cle, droits, quota ou credit
    if (isinstance(status, int) and status >= 500) or any(
        klass.__name__ == "APIConnectionError" for klass in type(exc).__mro__
    ):
        return "claude_unavailable"  # 5xx, surcharge, connexion ou delai depasse
    return "claude"


def _error_kind(exc: BaseException) -> str:
    """Classe une erreur d'ingestion sans importer les bibliotheques (par module et par classe).
    Seul ce libelle classe sort dans le digest, jamais le message brut."""
    for klass in type(exc).__mro__:
        module = klass.__module__ or ""
        name = klass.__name__
        if module.startswith("google.auth") and name == "RefreshError":
            return "gmail_auth"
        if module.startswith("googleapiclient"):
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
            try:
                status = int(status) if status is not None else None
            except (TypeError, ValueError):
                status = None
            return "gmail_auth" if status in (401, 403) else "gmail_api"
        if module.startswith("anthropic"):
            return _claude_error_kind(exc)
    if isinstance(exc, RuntimeError):
        message = str(exc)
        if "illisible" in message:
            return "token_unreadable"  # app/services.py : cle de chiffrement differente entre api et worker
        if "Jeton Gmail invalide ou absent" in message:
            return "gmail_auth"  # app/gmail_client.py : jeton d'un compte env a regenerer
    return "other"


def _beat(
    service: EmailService,
    scope: str,
    ok: bool | None = None,
    processed: int = 0,
    exc: BaseException | None = None,
) -> None:
    try:
        service.ctx.database.record_heartbeat(
            scope,
            ok=ok,
            processed=processed,
            error_kind=_error_kind(exc) if exc is not None else None,
            error_class=type(exc).__name__ if exc is not None else None,
        )
    except Exception as err:  # noqa: BLE001  (le heartbeat ne doit jamais arreter le worker)
        print(f"Heartbeat impossible ({scope}): {type(err).__name__}")


def run_once(service: EmailService) -> None:
    total = 0
    _beat(service, CYCLE)  # debut de cycle
    # Recharge les comptes ajoutes a chaud a chaque cycle.
    service.ctx.reload_accounts()
    for account in service.ctx.all_accounts():
        try:
            processed = service.ingest_account(account)
            total += processed
            _beat(service, account.id, ok=True, processed=processed)
        except Exception as exc:  # noqa: BLE001
            print(f"[{account.id}] Erreur d'ingestion: {exc}")
            _beat(service, account.id, ok=False, exc=exc)
    _beat(service, CYCLE, ok=True, processed=total)
    # TODO(Routines, D-032, lot L6) : rapprochement des reponses envoyees depuis Gmail
    # (fiche vision/docs/contrats-digest/mail_auto_reply.md §8.12). Non developpe : c'est un
    # ajout au-dela de D-036, a faire valider au lot L6. En attendant, Samo marque le mail
    # « Envoye » ou « Refuse » dans le tableau de bord pour faire taire le rappel.
    if total == 0:
        print("Aucun nouvel email a traiter.")


def main() -> None:
    context = build_context(build_gmail=True)
    service = EmailService(context)
    accounts = ", ".join(a.label or a.id for a in context.settings.accounts)
    print(
        f"Worker actif ({len(context.settings.accounts)} compte(s): {accounts}). "
        f"Verification toutes les {context.settings.poll_interval_seconds} secondes."
    )

    while True:
        try:
            run_once(service)
        except Exception as exc:  # noqa: BLE001
            print(f"Erreur: {exc}")
            _beat(service, CYCLE, ok=False, exc=exc)
        time.sleep(context.settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
