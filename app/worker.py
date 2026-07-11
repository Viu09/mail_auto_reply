from __future__ import annotations

import time

from app.services import EmailService, build_context


def run_once(service: EmailService) -> None:
    total = 0
    # Recharge les comptes ajoutes a chaud a chaque cycle.
    service.ctx.reload_accounts()
    for account in service.ctx.all_accounts():
        try:
            total += service.ingest_account(account)
        except Exception as exc:  # noqa: BLE001
            print(f"[{account.id}] Erreur d'ingestion: {exc}")
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
        time.sleep(context.settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
