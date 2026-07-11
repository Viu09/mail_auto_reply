from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from app.anthropic_client import AIClient
from app.config import AccountConfig, Settings, get_settings
from app.db import Database
from app.gmail_client import GmailClient
from app.models import EmailAnalysis, EmailMessage


PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class Context:
    settings: Settings
    database: Database
    ai: AIClient
    gmail_clients: dict[str, GmailClient]
    accounts_by_id: dict[str, AccountConfig]


def build_context(build_gmail: bool = True) -> Context:
    settings = get_settings()
    database = Database(settings.database_url)
    ai = AIClient(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        reply_language=settings.default_reply_language,
        enable_thinking=settings.enable_thinking,
    )

    accounts_by_id = {account.id: account for account in settings.accounts}
    gmail_clients: dict[str, GmailClient] = {}
    if build_gmail:
        for account in settings.accounts:
            try:
                gmail_clients[account.id] = GmailClient(account.gmail_credentials_path, account.gmail_token_path)
            except Exception as exc:  # noqa: BLE001
                # Ne pas empecher le demarrage si un compte a un token invalide.
                # Le client sera reconstruit a la demande ; l'erreur remontera au bon moment.
                print(f"[{account.id}] Gmail indisponible au demarrage (token a regenerer ?): {exc}")

    return Context(
        settings=settings,
        database=database,
        ai=ai,
        gmail_clients=gmail_clients,
        accounts_by_id=accounts_by_id,
    )


class EmailNotFound(Exception):
    pass


class AccountNotFound(Exception):
    pass


class EmailService:
    def __init__(self, context: Context) -> None:
        self.ctx = context

    # -------------------------------------------------------------- ingestion

    def ingest_account(self, account: AccountConfig) -> int:
        gmail = self._gmail(account.id)
        max_ingest = self.ctx.settings.max_ingest_per_cycle

        processed = self._ingest_new(account, gmail, max_ingest)
        if processed < max_ingest:
            processed += self._backfill(account, gmail, max_ingest - processed)
        return processed

    def _ingest_new(self, account: AccountConfig, gmail: GmailClient, budget: int) -> int:
        """Traite les nouveaux emails en haut de boite jusqu'a rejoindre la zone deja connue."""
        processed = 0
        scanned = 0
        consecutive_known = 0
        page_token: str | None = None

        while processed < budget and scanned < 500:
            ids, page_token = gmail.list_message_ids(account.gmail_query, page_token, page_size=100)
            if not ids:
                break
            for message_id in ids:
                scanned += 1
                if self.ctx.database.has_processed(message_id):
                    consecutive_known += 1
                    if consecutive_known >= 100:
                        return processed
                    continue
                consecutive_known = 0
                self.ingest_message(account, message_id)
                processed += 1
                if processed >= budget:
                    break
            if page_token is None:
                break
        return processed

    def _backfill(self, account: AccountConfig, gmail: GmailClient, budget: int) -> int:
        """Remonte progressivement tout l'historique via un curseur de page persistant."""
        if budget <= 0:
            return 0
        state = self.ctx.database.get_ingest_state(account.id)
        if state["backfill_done"]:
            return 0

        processed = 0
        token = state["backfill_page_token"]

        while processed < budget:
            ids, next_token = gmail.list_message_ids(account.gmail_query, token, page_size=100)
            if not ids:
                self.ctx.database.set_ingest_state(account.id, None, True)
                break

            page_complete = True
            for message_id in ids:
                if self.ctx.database.has_processed(message_id):
                    continue
                self.ingest_message(account, message_id)
                processed += 1
                if processed >= budget:
                    page_complete = False
                    break

            if not page_complete:
                # On garde le meme token : la page sera reprise (la dedup ignore le deja traite).
                self.ctx.database.set_ingest_state(account.id, token, False)
                break
            if next_token is None:
                self.ctx.database.set_ingest_state(account.id, None, True)
                break
            token = next_token
            self.ctx.database.set_ingest_state(account.id, token, False)

        return processed

    def ingest_message(self, account: AccountConfig, message_id: str) -> dict:
        gmail = self._gmail(account.id)
        email = gmail.get_message(message_id, account_id=account.id)
        attachments = self._prepare_incoming_attachments(account, gmail, email)
        memory = self.ctx.database.list_recent_reply_memory(account.id, limit=3)
        known_categories = [c["name"] for c in self.ctx.database.email_categories()][:40]

        analysis = self.ctx.ai.analyze_email(
            email=email,
            reply_language=account.reply_language,
            signature=account.signature,
            attachments=attachments,
            memory_examples=memory,
            known_categories=known_categories,
        )
        target_language = analysis.target_language or account.reply_language
        aliases = self.ctx.database.get_category_aliases("email")
        category = aliases.get(analysis.category, analysis.category) or "Autre"
        analysis = replace(
            analysis,
            category=category,
            suggested_reply=ensure_email_signature(
                normalize_reply_text(analysis.suggested_reply), account.signature
            ),
        )

        record = self.ctx.database.create_email(email, analysis, target_language)
        self._store_documents(account, email, attachments, category, record["id"])
        record = self._apply_rules(account, record, email)

        print(f"[{account.id}] {record['approval_status']:8} | {record['priority']:6} | {email.subject}")
        return record

    def _apply_rules(self, account: AccountConfig, record: dict, email: EmailMessage) -> dict:
        rules = self.ctx.database.list_rules(account_id=account.id, enabled_only=True)
        for rule in rules:
            if not self._rule_matches(rule, record):
                continue
            action = rule.get("action")
            if action == "auto_reject":
                return self.ctx.database.update_status(record["id"], "rejected") or record
            if action == "auto_send" and record.get("should_reply") and record.get("suggested_reply"):
                return self.send(record["id"], email=email, account=account)
        return record

    @staticmethod
    def _rule_matches(rule: dict, record: dict) -> bool:
        if rule.get("category") and rule["category"] != record.get("category"):
            return False
        max_priority = rule.get("max_priority")
        if max_priority:
            if PRIORITY_ORDER.get(record.get("priority"), 1) > PRIORITY_ORDER.get(max_priority, 2):
                return False
        return True

    # -------------------------------------------------------------- lecture

    def list_emails(self, **filters) -> list[dict]:
        return self.ctx.database.list_emails(**filters)

    def account_summary(self) -> list[dict]:
        summary = {row["account_id"]: row for row in self.ctx.database.account_summary()}
        results = []
        for account in self.ctx.settings.accounts:
            base = summary.get(account.id, {"account_id": account.id, "pending": 0, "sent": 0, "rejected": 0, "total": 0})
            results.append({**base, "label": account.label or account.id})
        return results

    def get_email(self, email_id: int) -> dict:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        record["attachments"] = self.ctx.database.list_attachments(email_id)
        return record

    # -------------------------------------------------------------- actions

    def update_reply(self, email_id: int, reply_text: str) -> dict:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        signature = self._signature(record["account_id"])
        cleaned = ensure_email_signature(normalize_reply_text(reply_text), signature)
        return self.ctx.database.update_reply(email_id, cleaned)

    def refine_reply(self, email_id: int, instructions: str) -> dict:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        account = self.ctx.accounts_by_id.get(record["account_id"])
        signature = account.signature if account else "Samo Ferman"
        target_language = record.get("target_language") or (account.reply_language if account else "fr")
        email = _email_from_record(record)
        refined = self.ctx.ai.refine_reply(
            email=email,
            current_reply=record["suggested_reply"],
            instructions=instructions,
            target_language=target_language,
            signature=signature,
            attachment_analysis=record.get("attachment_analysis") or "",
        )
        cleaned = ensure_email_signature(normalize_reply_text(refined), signature)
        return self.ctx.database.update_reply(email_id, cleaned)

    def reject(self, email_id: int) -> dict:
        record = self.ctx.database.update_status(email_id, "rejected")
        if record is None:
            raise EmailNotFound(str(email_id))
        return record

    def mark_read(self, email_id: int) -> dict:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        gmail = self._gmail(record["account_id"])
        try:
            gmail.mark_as_read(record["gmail_id"])
        except Exception as exc:  # noqa: BLE001
            print(f"Marquage lu impossible pour {email_id}: {exc}")
        updated = self.ctx.database.set_marked_read(email_id, True)
        return updated or record

    def send(
        self,
        email_id: int,
        email: EmailMessage | None = None,
        account: AccountConfig | None = None,
    ) -> dict:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        if record["approval_status"] == "sent":
            return record

        account = account or self.ctx.accounts_by_id.get(record["account_id"])
        if account is None:
            raise AccountNotFound(record["account_id"])
        gmail = self._gmail(account.id)

        email = email or _email_from_record(record)
        signature = account.signature
        reply = ensure_email_signature(normalize_reply_text(record["suggested_reply"]), signature)
        attachment_paths = [item["local_path"] for item in self.ctx.database.list_attachments(email_id)]

        sent_message_id = gmail.send_reply(email, reply, attachment_paths)
        updated = self.ctx.database.update_status(email_id, "sent", sent_message_id)

        self.ctx.database.save_reply_memory(
            account_id=account.id,
            category=record.get("category") or "Autre",
            tags=record.get("tags") or [],
            sender=record.get("sender") or "",
            subject=record.get("subject") or "",
            email_body=record.get("body_text") or "",
            final_reply=reply,
        )
        return updated or record

    # -------------------------------------------------------------- pieces jointes

    def add_outbound_attachment(self, email_id: int, file_name: str, content: bytes, mime_type: str | None) -> dict:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        safe_name = Path(file_name).name or "piece_jointe"
        destination = (
            self.ctx.settings.data_dir
            / "outbound_attachments"
            / record["account_id"]
            / str(email_id)
            / safe_name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return self.ctx.database.add_attachment(email_id, safe_name, str(destination), mime_type)

    def list_outbound_attachments(self, email_id: int) -> list[dict]:
        return self.ctx.database.list_attachments(email_id)

    def get_incoming_attachment(self, email_id: int, file_name: str) -> tuple[Path, str]:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        safe_name = Path(file_name).name
        base_dir = self.ctx.settings.data_dir / "incoming_attachments" / record["account_id"] / record["gmail_id"]
        path = base_dir / safe_name

        if not path.exists():
            gmail = self._gmail(record["account_id"])
            source = gmail.get_message(record["gmail_id"], account_id=record["account_id"])
            match = next((a for a in source.attachments if a.filename == safe_name), None)
            if match is None:
                raise EmailNotFound(f"{email_id}:{safe_name}")
            gmail.download_attachment(record["gmail_id"], match, path)

        mime_type = _guess_mime(safe_name)
        return path, mime_type

    # -------------------------------------------------------------- suppression

    def delete_email(self, email_id: int) -> dict:
        record = self.ctx.database.get_email(email_id)
        if record is None:
            raise EmailNotFound(str(email_id))
        try:
            gmail = self._gmail(record["account_id"])
            if record.get("gmail_id"):
                gmail.trash_message(record["gmail_id"])
        except Exception as exc:  # noqa: BLE001
            print(f"Corbeille Gmail impossible pour {email_id}: {exc}")
        self.ctx.database.delete_email(email_id)
        return {"ok": True, "id": email_id}

    # -------------------------------------------------------------- categories

    def email_categories(self, account_id: str | None = None, status: str | None = None) -> list[dict]:
        return self.ctx.database.email_categories(account_id, status)

    def recategorize_pending(self, only_other: bool = True) -> int:
        return self.ctx.database.count_to_recategorize(only_other=only_other)

    def recategorize_emails(self, only_other: bool = True, max_emails: int = 150) -> dict:
        """Reclasse par lots les emails (par defaut ceux en 'Autre') via une passe IA legere."""
        aliases = self.ctx.database.get_category_aliases("email")
        total_updated = 0
        processed = 0
        batch_size = 25
        while processed < max_emails:
            items = self.ctx.database.emails_to_recategorize(only_other=only_other, limit=batch_size)
            if not items:
                break
            known = [c["name"] for c in self.ctx.database.email_categories() if c["name"] != "Autre"][:40]
            mapping = self.ctx.ai.classify_categories(items, known_categories=known)
            resolved = {}
            for cid, category in mapping.items():
                category = aliases.get(category, category)
                if category and category != "Autre":
                    resolved[cid] = category
            total_updated += self.ctx.database.set_email_categories(resolved)
            # Chaque email n'est tente qu'une fois (evite de reclasser en boucle les vrais 'Autre').
            self.ctx.database.mark_recategorized([item["id"] for item in items])
            processed += len(items)
        remaining = self.ctx.database.count_to_recategorize(only_other=only_other)
        return {"updated": total_updated, "remaining": remaining}

    def rename_email_category(self, from_name: str, to_name: str) -> dict:
        from_name = (from_name or "").strip()
        to_name = (to_name or "").strip()
        if not from_name or not to_name or from_name == to_name:
            return {"updated": 0}
        self.ctx.database.add_category_alias("email", from_name, to_name)
        updated = self.ctx.database.rename_email_category(from_name, to_name)
        return {"updated": updated}

    # -------------------------------------------------------------- documents

    def list_documents(self, **filters) -> list[dict]:
        return self.ctx.database.list_documents(**filters)

    def document_categories(self, account_id: str | None = None) -> list[dict]:
        return self.ctx.database.document_categories(account_id)

    def rename_document_category(self, from_name: str, to_name: str) -> dict:
        from_name = (from_name or "").strip()
        to_name = (to_name or "").strip()
        if not from_name or not to_name or from_name == to_name:
            return {"updated": 0}
        self.ctx.database.add_category_alias("document", from_name, to_name)
        updated = self.ctx.database.rename_document_category(from_name, to_name)
        return {"updated": updated}

    def get_document_download(self, document_id: int) -> tuple[Path, str, str]:
        record = self.ctx.database.get_document(document_id)
        if record is None:
            raise EmailNotFound(str(document_id))
        path = self._ensure_document_file(record)
        mime_type = record.get("mime_type") or _guess_mime(record["file_name"])
        return path, mime_type, record["file_name"]

    def summarize_document(self, document_id: int) -> dict:
        record = self.ctx.database.get_document(document_id)
        if record is None:
            raise EmailNotFound(str(document_id))
        path = self._ensure_document_file(record)
        mime_type = record.get("mime_type") or _guess_mime(record["file_name"])
        known = [c["name"] for c in self.ctx.database.document_categories()][:40]
        result = self.ctx.ai.summarize_document(
            path=path,
            mime_type=mime_type,
            filename=record["file_name"],
            known_categories=known,
            context=record.get("subject") or "",
        )
        aliases = self.ctx.database.get_category_aliases("document")
        category = aliases.get(result["category"], result["category"]) or record.get("category") or "Autre"
        updated = self.ctx.database.update_document(
            document_id, summary=result["summary"], category=category
        )
        return updated or record

    def delete_document(self, document_id: int) -> dict:
        record = self.ctx.database.delete_document(document_id)
        if record is None:
            raise EmailNotFound(str(document_id))
        try:
            Path(record["local_path"]).unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(f"Suppression fichier impossible ({record.get('local_path')}): {exc}")
        return {"ok": True, "id": document_id}

    def _ensure_document_file(self, record: dict) -> Path:
        path = Path(record["local_path"])
        if path.exists():
            return path
        gmail_id = record.get("gmail_id")
        if not gmail_id:
            raise EmailNotFound(f"document:{record.get('id')}")
        gmail = self._gmail(record["account_id"])
        source = gmail.get_message(gmail_id, account_id=record["account_id"])
        match = next((a for a in source.attachments if a.filename == record["file_name"]), None)
        if match is None:
            raise EmailNotFound(f"document:{record.get('id')}")
        gmail.download_attachment(gmail_id, match, path)
        return path

    def _store_documents(
        self,
        account: AccountConfig,
        email: EmailMessage,
        attachments: list[dict],
        email_category: str,
        email_id: int,
    ) -> None:
        for item in attachments:
            path = item["path"]
            filename = item.get("filename") or Path(path).name
            if self.ctx.database.document_exists(email.gmail_id, filename):
                continue
            try:
                size = Path(path).stat().st_size
            except OSError:
                size = 0
            category = _auto_document_category(filename, item.get("mime_type") or "", email_category)
            self.ctx.database.create_document(
                {
                    "account_id": account.id,
                    "email_id": email_id,
                    "gmail_id": email.gmail_id,
                    "file_name": filename,
                    "local_path": str(path),
                    "mime_type": item.get("mime_type"),
                    "size_bytes": size,
                    "category": category,
                    "sender": email.sender,
                    "subject": email.subject,
                    "received_at": email.received_at,
                }
            )

    # -------------------------------------------------------------- regles

    def list_rules(self) -> list[dict]:
        return self.ctx.database.list_rules()

    def create_rule(self, data: dict) -> dict:
        return self.ctx.database.create_rule(data)

    def update_rule(self, rule_id: int, data: dict) -> dict | None:
        return self.ctx.database.update_rule(rule_id, data)

    def delete_rule(self, rule_id: int) -> bool:
        return self.ctx.database.delete_rule(rule_id)

    # -------------------------------------------------------------- interne

    def _gmail(self, account_id: str) -> GmailClient:
        gmail = self.ctx.gmail_clients.get(account_id)
        if gmail is None:
            account = self.ctx.accounts_by_id.get(account_id)
            if account is None:
                raise AccountNotFound(account_id)
            gmail = GmailClient(account.gmail_credentials_path, account.gmail_token_path)
            self.ctx.gmail_clients[account_id] = gmail
        return gmail

    def _signature(self, account_id: str) -> str:
        account = self.ctx.accounts_by_id.get(account_id)
        return account.signature if account else "Samo Ferman"

    def _prepare_incoming_attachments(self, account: AccountConfig, gmail: GmailClient, email: EmailMessage) -> list[dict]:
        if not email.attachments:
            return []
        base_dir = self.ctx.settings.data_dir / "incoming_attachments" / account.id / email.gmail_id
        prepared: list[dict] = []
        for attachment in email.attachments:
            destination = base_dir / attachment.filename
            try:
                if not destination.exists():
                    gmail.download_attachment(email.gmail_id, attachment, destination)
                prepared.append(
                    {"path": destination, "mime_type": attachment.mime_type, "filename": attachment.filename}
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Piece jointe {attachment.filename} indisponible: {exc}")
        return prepared


# ------------------------------------------------------------------ helpers texte


def normalize_reply_text(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    blocks: list[str] = []
    for block in cleaned.split("\n\n"):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        is_list = all(
            line.startswith("- ") or line.startswith("* ") or re.match(r"^\d+\.\s", line)
            for line in lines
        )
        blocks.append("\n".join(lines) if is_list else " ".join(lines))

    return "\n\n".join(blocks)


def ensure_email_signature(text: str, signature: str) -> str:
    normalized = (text or "").strip()
    if not signature:
        return normalized
    if normalized.endswith(signature):
        return normalized
    return f"{normalized}\n\n{signature}"


def _email_from_record(record: dict) -> EmailMessage:
    return EmailMessage(
        gmail_id=record["gmail_id"],
        thread_id=record["thread_id"],
        subject=record["subject"],
        sender=record["sender"],
        snippet=record["snippet"],
        body_text=record.get("body_text") or "",
        attachment_names=record.get("attachment_names") or [],
        reply_to=record.get("reply_to") or record["sender"],
        internet_message_id=record.get("internet_message_id") or "",
        attachments=[],
        account_id=record.get("account_id") or "default",
    )


_DOC_KEYWORDS = [
    ("Facture", ("facture", "invoice", "recu", "receipt", "ticket")),
    ("Devis", ("devis", "quote", "estimation")),
    ("Contrat", ("contrat", "contract", "bail", "mandat", "convention")),
    ("Releve", ("releve", "statement", "compte")),
    ("Attestation", ("attestation", "certificat", "certificate", "justificatif")),
    ("CV", ("cv", "resume", "curriculum")),
]

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tiff"}


def _auto_document_category(filename: str, mime_type: str, email_category: str) -> str:
    lower = filename.lower()
    for label, keywords in _DOC_KEYWORDS:
        if any(keyword in lower for keyword in keywords):
            return label
    suffix = Path(filename).suffix.lower()
    if suffix in _IMAGE_EXT or mime_type.startswith("image/"):
        return "Photo"
    return email_category or "Autre"


def _guess_mime(file_name: str) -> str:
    import mimetypes

    mime, _ = mimetypes.guess_type(file_name)
    return mime or "application/octet-stream"
