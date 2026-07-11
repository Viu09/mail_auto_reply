from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from app.models import EmailAnalysis, EmailMessage


Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProcessedEmail(Base):
    __tablename__ = "processed_emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, default="default", index=True)
    gmail_id = Column(String(128), nullable=False, unique=True, index=True)
    thread_id = Column(String(128), nullable=False, default="")
    sender = Column(String(512), nullable=False, default="")
    reply_to = Column(String(512), nullable=False, default="")
    internet_message_id = Column(String(512), nullable=False, default="")
    subject = Column(String(1024), nullable=False, default="")
    snippet = Column(Text, nullable=False, default="")
    body_text = Column(Text, nullable=False, default="")
    attachment_names = Column(JSON, nullable=False, default=list)
    attachment_analysis = Column(Text, nullable=False, default="")
    summary = Column(Text, nullable=False, default="")
    detailed_summary = Column(Text, nullable=False, default="")
    category = Column(String(64), nullable=False, default="Autre")
    tags = Column(JSON, nullable=False, default=list)
    priority = Column(String(16), nullable=False, default="medium")
    suggested_reply = Column(Text, nullable=False, default="")
    should_reply = Column(Boolean, nullable=False, default=True)
    required_documents = Column(JSON, nullable=False, default=list)
    provided_documents = Column(JSON, nullable=False, default=list)
    target_language = Column(String(64), nullable=False, default="")
    approval_status = Column(String(16), nullable=False, default="pending", index=True)
    sent_message_id = Column(String(128), nullable=True)
    marked_read = Column(Boolean, nullable=False, default=False)
    received_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    attachments = relationship(
        "OutboundAttachment",
        back_populates="email",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "gmail_id": self.gmail_id,
            "thread_id": self.thread_id,
            "sender": self.sender,
            "reply_to": self.reply_to,
            "internet_message_id": self.internet_message_id,
            "subject": self.subject,
            "snippet": self.snippet,
            "body_text": self.body_text,
            "attachment_names": self.attachment_names or [],
            "attachment_analysis": self.attachment_analysis,
            "summary": self.summary,
            "detailed_summary": self.detailed_summary,
            "category": self.category,
            "tags": self.tags or [],
            "priority": self.priority,
            "suggested_reply": self.suggested_reply,
            "should_reply": self.should_reply,
            "required_documents": self.required_documents or [],
            "provided_documents": self.provided_documents or [],
            "target_language": self.target_language,
            "approval_status": self.approval_status,
            "sent_message_id": self.sent_message_id,
            "marked_read": self.marked_read,
            "received_at": _iso(self.received_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class OutboundAttachment(Base):
    __tablename__ = "outbound_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(Integer, ForeignKey("processed_emails.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(512), nullable=False)
    local_path = Column(String(1024), nullable=False)
    mime_type = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    email = relationship("ProcessedEmail", back_populates="attachments")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email_id": self.email_id,
            "file_name": self.file_name,
            "local_path": self.local_path,
            "mime_type": self.mime_type,
            "created_at": _iso(self.created_at),
        }


class ReplyMemory(Base):
    __tablename__ = "reply_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, default="default", index=True)
    category = Column(String(64), nullable=False, index=True)
    tags = Column(JSON, nullable=False, default=list)
    sender = Column(String(512), nullable=True)
    subject = Column(String(1024), nullable=True)
    email_body = Column(Text, nullable=False, default="")
    final_reply = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "category": self.category,
            "tags": self.tags or [],
            "sender": self.sender,
            "subject": self.subject,
            "email_body": self.email_body,
            "final_reply": self.final_reply,
            "created_at": _iso(self.created_at),
        }


class Document(Base):
    """Fichier recu en piece jointe, stocke durablement et categorise."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=False, default="default", index=True)
    email_id = Column(Integer, ForeignKey("processed_emails.id", ondelete="SET NULL"), nullable=True, index=True)
    gmail_id = Column(String(128), nullable=False, default="", index=True)
    file_name = Column(String(512), nullable=False)
    local_path = Column(String(1024), nullable=False)
    mime_type = Column(String(128), nullable=True)
    size_bytes = Column(Integer, nullable=False, default=0)
    category = Column(String(64), nullable=False, default="Autre", index=True)
    summary = Column(Text, nullable=False, default="")
    sender = Column(String(512), nullable=False, default="")
    subject = Column(String(1024), nullable=False, default="")
    received_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "email_id": self.email_id,
            "gmail_id": self.gmail_id,
            "file_name": self.file_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes or 0,
            "category": self.category,
            "summary": self.summary,
            "sender": self.sender,
            "subject": self.subject,
            "received_at": _iso(self.received_at),
            "created_at": _iso(self.created_at),
        }


class CategoryAlias(Base):
    """Regle de renommage/fusion de categorie, persistee pour s'appliquer aux futurs elements."""

    __tablename__ = "category_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(16), nullable=False, default="email", index=True)  # email | document
    from_name = Column(String(64), nullable=False)
    to_name = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class IngestState(Base):
    """Curseur de backfill par compte pour remonter tout l'historique Gmail."""

    __tablename__ = "ingest_state"

    account_id = Column(String(64), primary_key=True)
    backfill_page_token = Column(Text, nullable=True)
    backfill_done = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(64), nullable=True)  # None => tous les comptes
    name = Column(String(256), nullable=False, default="")
    category = Column(String(64), nullable=True)  # None => toutes les categories
    max_priority = Column(String(16), nullable=True)  # ne s'applique qu'en dessous ou egal
    action = Column(String(32), nullable=False, default="flag")  # auto_send | auto_reject | flag
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "name": self.name,
            "category": self.category,
            "max_priority": self.max_priority,
            "action": self.action,
            "enabled": self.enabled,
            "created_at": _iso(self.created_at),
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class Database:
    def __init__(self, database_url: str) -> None:
        connect_args = {}
        if database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        self.engine = create_engine(
            database_url,
            connect_args=connect_args,
            pool_pre_ping=not database_url.startswith("sqlite"),
            future=True,
        )
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(self.engine)
        self._run_migrations()

    def _run_migrations(self) -> None:
        # Ajoute les colonnes introduites apres la creation initiale de la table.
        # create_all ne modifie pas une table existante ; on complete a la main (Postgres).
        if self.engine.dialect.name != "postgresql":
            return
        statements = [
            "ALTER TABLE processed_emails ADD COLUMN IF NOT EXISTS received_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE processed_emails ADD COLUMN IF NOT EXISTS marked_read BOOLEAN NOT NULL DEFAULT FALSE",
        ]
        with self.engine.begin() as connection:
            for statement in statements:
                try:
                    connection.execute(text(statement))
                except Exception as exc:  # noqa: BLE001
                    print(f"Migration ignoree ({statement}): {exc}")

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------- ingestion

    def has_processed(self, gmail_id: str) -> bool:
        with self.session() as session:
            row = session.execute(
                select(ProcessedEmail.id).where(ProcessedEmail.gmail_id == gmail_id)
            ).first()
        return row is not None

    def create_email(self, email: EmailMessage, analysis: EmailAnalysis, target_language: str) -> dict:
        with self.session() as session:
            record = ProcessedEmail(
                account_id=email.account_id,
                gmail_id=email.gmail_id,
                thread_id=email.thread_id,
                sender=email.sender,
                reply_to=email.reply_to or email.sender,
                internet_message_id=email.internet_message_id,
                subject=email.subject,
                snippet=email.snippet,
                body_text=email.body_text,
                attachment_names=list(email.attachment_names),
                attachment_analysis=analysis.attachment_analysis,
                summary=analysis.summary,
                detailed_summary=analysis.detailed_summary,
                category=analysis.category,
                tags=list(analysis.tags),
                priority=analysis.priority,
                suggested_reply=analysis.suggested_reply,
                should_reply=analysis.should_reply,
                required_documents=list(analysis.required_documents),
                provided_documents=list(analysis.provided_documents),
                target_language=target_language,
                approval_status="pending",
                received_at=email.received_at,
            )
            session.add(record)
            session.flush()
            return record.to_dict()

    # ------------------------------------------------------------- lecture

    def get_email(self, email_id: int) -> dict | None:
        with self.session() as session:
            record = session.get(ProcessedEmail, email_id)
            return record.to_dict() if record else None

    def list_emails(
        self,
        account_id: str | None = None,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        with self.session() as session:
            query = select(ProcessedEmail)
            if account_id:
                query = query.where(ProcessedEmail.account_id == account_id)
            if status:
                query = query.where(ProcessedEmail.approval_status == status)
            if category:
                query = query.where(ProcessedEmail.category == category)
            if priority:
                query = query.where(ProcessedEmail.priority == priority)
            if search:
                like = f"%{search}%"
                query = query.where(
                    ProcessedEmail.subject.ilike(like) | ProcessedEmail.sender.ilike(like)
                )
            query = query.order_by(
                func.coalesce(ProcessedEmail.received_at, ProcessedEmail.created_at).desc()
            ).limit(limit).offset(offset)
            rows = session.execute(query).scalars().all()
            return [row.to_dict() for row in rows]

    def account_summary(self) -> list[dict]:
        with self.session() as session:
            rows = session.execute(
                select(
                    ProcessedEmail.account_id,
                    ProcessedEmail.approval_status,
                    func.count(ProcessedEmail.id),
                ).group_by(ProcessedEmail.account_id, ProcessedEmail.approval_status)
            ).all()

        summary: dict[str, dict] = {}
        for account_id, status, count in rows:
            bucket = summary.setdefault(account_id, {"account_id": account_id, "pending": 0, "sent": 0, "rejected": 0, "total": 0})
            bucket[status] = bucket.get(status, 0) + count
            bucket["total"] += count
        return list(summary.values())

    # ------------------------------------------------------------- mutations

    def update_reply(self, email_id: int, suggested_reply: str) -> dict | None:
        with self.session() as session:
            record = session.get(ProcessedEmail, email_id)
            if record is None:
                return None
            record.suggested_reply = suggested_reply
            session.flush()
            return record.to_dict()

    def update_status(self, email_id: int, status: str, sent_message_id: str | None = None) -> dict | None:
        with self.session() as session:
            record = session.get(ProcessedEmail, email_id)
            if record is None:
                return None
            record.approval_status = status
            if sent_message_id is not None:
                record.sent_message_id = sent_message_id
            session.flush()
            return record.to_dict()

    def set_marked_read(self, email_id: int, value: bool = True) -> dict | None:
        with self.session() as session:
            record = session.get(ProcessedEmail, email_id)
            if record is None:
                return None
            record.marked_read = value
            session.flush()
            return record.to_dict()

    # ------------------------------------------------------------- pieces jointes

    def add_attachment(self, email_id: int, file_name: str, local_path: str, mime_type: str | None) -> dict:
        with self.session() as session:
            record = OutboundAttachment(
                email_id=email_id,
                file_name=file_name,
                local_path=local_path,
                mime_type=mime_type,
            )
            session.add(record)
            session.flush()
            return record.to_dict()

    def list_attachments(self, email_id: int) -> list[dict]:
        with self.session() as session:
            rows = session.execute(
                select(OutboundAttachment)
                .where(OutboundAttachment.email_id == email_id)
                .order_by(OutboundAttachment.id.asc())
            ).scalars().all()
            return [row.to_dict() for row in rows]

    # ------------------------------------------------------------- memoire

    def save_reply_memory(
        self,
        account_id: str,
        category: str,
        tags: list[str],
        sender: str,
        subject: str,
        email_body: str,
        final_reply: str,
    ) -> None:
        with self.session() as session:
            session.add(
                ReplyMemory(
                    account_id=account_id,
                    category=category,
                    tags=list(tags),
                    sender=sender,
                    subject=subject,
                    email_body=email_body,
                    final_reply=final_reply,
                )
            )

    def list_recent_reply_memory(self, account_id: str, limit: int = 3) -> list[dict]:
        with self.session() as session:
            rows = session.execute(
                select(ReplyMemory)
                .where(ReplyMemory.account_id == account_id)
                .order_by(ReplyMemory.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return [row.to_dict() for row in rows]

    # ------------------------------------------------------------- regles

    def list_rules(self, account_id: str | None = None, enabled_only: bool = False) -> list[dict]:
        with self.session() as session:
            query = select(AutomationRule)
            if account_id is not None:
                query = query.where(
                    (AutomationRule.account_id == account_id) | (AutomationRule.account_id.is_(None))
                )
            if enabled_only:
                query = query.where(AutomationRule.enabled.is_(True))
            rows = session.execute(query.order_by(AutomationRule.created_at.desc())).scalars().all()
            return [row.to_dict() for row in rows]

    def create_rule(self, data: dict) -> dict:
        with self.session() as session:
            record = AutomationRule(
                account_id=data.get("account_id"),
                name=data.get("name") or "",
                category=data.get("category"),
                max_priority=data.get("max_priority"),
                action=data.get("action") or "flag",
                enabled=bool(data.get("enabled", True)),
            )
            session.add(record)
            session.flush()
            return record.to_dict()

    def update_rule(self, rule_id: int, data: dict) -> dict | None:
        with self.session() as session:
            record = session.get(AutomationRule, rule_id)
            if record is None:
                return None
            for key in ("account_id", "name", "category", "max_priority", "action", "enabled"):
                if key in data:
                    setattr(record, key, data[key])
            session.flush()
            return record.to_dict()

    def delete_rule(self, rule_id: int) -> bool:
        with self.session() as session:
            record = session.get(AutomationRule, rule_id)
            if record is None:
                return False
            session.delete(record)
            return True

    # ------------------------------------------------------------- suppression email

    def delete_email(self, email_id: int) -> dict | None:
        """Supprime l'email de la base. Les documents lies sont conserves (email_id => NULL)."""
        with self.session() as session:
            record = session.get(ProcessedEmail, email_id)
            if record is None:
                return None
            data = record.to_dict()
            for doc in session.execute(
                select(Document).where(Document.email_id == email_id)
            ).scalars().all():
                doc.email_id = None
            session.delete(record)
            return data

    # ------------------------------------------------------------- categories emails

    def email_categories(self, account_id: str | None = None, status: str | None = None) -> list[dict]:
        with self.session() as session:
            query = select(ProcessedEmail.category, func.count(ProcessedEmail.id))
            if account_id:
                query = query.where(ProcessedEmail.account_id == account_id)
            if status:
                query = query.where(ProcessedEmail.approval_status == status)
            query = query.group_by(ProcessedEmail.category)
            rows = session.execute(query).all()
        return [
            {"name": name or "Autre", "count": count}
            for name, count in sorted(rows, key=lambda r: (-r[1], (r[0] or "").lower()))
        ]

    def rename_email_category(self, from_name: str, to_name: str) -> int:
        with self.session() as session:
            rows = session.execute(
                select(ProcessedEmail).where(ProcessedEmail.category == from_name)
            ).scalars().all()
            for row in rows:
                row.category = to_name
            return len(rows)

    # ------------------------------------------------------------- documents

    def create_document(self, data: dict) -> dict:
        with self.session() as session:
            record = Document(
                account_id=data.get("account_id") or "default",
                email_id=data.get("email_id"),
                gmail_id=data.get("gmail_id") or "",
                file_name=data.get("file_name") or "fichier",
                local_path=data.get("local_path") or "",
                mime_type=data.get("mime_type"),
                size_bytes=int(data.get("size_bytes") or 0),
                category=data.get("category") or "Autre",
                summary=data.get("summary") or "",
                sender=data.get("sender") or "",
                subject=data.get("subject") or "",
                received_at=data.get("received_at"),
            )
            session.add(record)
            session.flush()
            return record.to_dict()

    def document_exists(self, gmail_id: str, file_name: str) -> bool:
        with self.session() as session:
            row = session.execute(
                select(Document.id).where(
                    Document.gmail_id == gmail_id, Document.file_name == file_name
                )
            ).first()
        return row is not None

    def get_document(self, document_id: int) -> dict | None:
        with self.session() as session:
            record = session.get(Document, document_id)
            if record is None:
                return None
            data = record.to_dict()
            data["local_path"] = record.local_path
            return data

    def list_documents(
        self,
        account_id: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        with self.session() as session:
            query = select(Document)
            if account_id:
                query = query.where(Document.account_id == account_id)
            if category:
                query = query.where(Document.category == category)
            if search:
                like = f"%{search}%"
                query = query.where(
                    Document.file_name.ilike(like)
                    | Document.sender.ilike(like)
                    | Document.subject.ilike(like)
                )
            query = query.order_by(
                func.coalesce(Document.received_at, Document.created_at).desc()
            ).limit(limit).offset(offset)
            rows = session.execute(query).scalars().all()
            return [row.to_dict() for row in rows]

    def document_categories(self, account_id: str | None = None) -> list[dict]:
        with self.session() as session:
            query = select(Document.category, func.count(Document.id))
            if account_id:
                query = query.where(Document.account_id == account_id)
            query = query.group_by(Document.category)
            rows = session.execute(query).all()
        return [
            {"name": name or "Autre", "count": count}
            for name, count in sorted(rows, key=lambda r: (-r[1], (r[0] or "").lower()))
        ]

    def update_document(self, document_id: int, **fields) -> dict | None:
        with self.session() as session:
            record = session.get(Document, document_id)
            if record is None:
                return None
            for key, value in fields.items():
                if value is not None and hasattr(record, key):
                    setattr(record, key, value)
            session.flush()
            return record.to_dict()

    def rename_document_category(self, from_name: str, to_name: str) -> int:
        with self.session() as session:
            rows = session.execute(
                select(Document).where(Document.category == from_name)
            ).scalars().all()
            for row in rows:
                row.category = to_name
            return len(rows)

    def delete_document(self, document_id: int) -> dict | None:
        with self.session() as session:
            record = session.get(Document, document_id)
            if record is None:
                return None
            data = record.to_dict()
            data["local_path"] = record.local_path
            session.delete(record)
            return data

    # ------------------------------------------------------------- alias categories

    def get_category_aliases(self, scope: str) -> dict[str, str]:
        with self.session() as session:
            rows = session.execute(
                select(CategoryAlias.from_name, CategoryAlias.to_name).where(
                    CategoryAlias.scope == scope
                )
            ).all()
        return {frm: to for frm, to in rows}

    def add_category_alias(self, scope: str, from_name: str, to_name: str) -> None:
        with self.session() as session:
            existing = session.execute(
                select(CategoryAlias).where(
                    CategoryAlias.scope == scope, CategoryAlias.from_name == from_name
                )
            ).scalars().first()
            if existing:
                existing.to_name = to_name
            else:
                session.add(CategoryAlias(scope=scope, from_name=from_name, to_name=to_name))

    # ------------------------------------------------------------- backfill

    def get_ingest_state(self, account_id: str) -> dict:
        with self.session() as session:
            record = session.get(IngestState, account_id)
            if record is None:
                record = IngestState(account_id=account_id, backfill_page_token=None, backfill_done=False)
                session.add(record)
                session.flush()
            return {
                "account_id": record.account_id,
                "backfill_page_token": record.backfill_page_token,
                "backfill_done": record.backfill_done,
            }

    def set_ingest_state(self, account_id: str, page_token: str | None, done: bool) -> None:
        with self.session() as session:
            record = session.get(IngestState, account_id)
            if record is None:
                record = IngestState(account_id=account_id)
                session.add(record)
            record.backfill_page_token = page_token
            record.backfill_done = done
