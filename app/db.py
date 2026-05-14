from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.models import EmailAnalysis, EmailMessage


SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_emails (
    gmail_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    reply_to TEXT NOT NULL DEFAULT '',
    internet_message_id TEXT NOT NULL DEFAULT '',
    telegram_ref TEXT NOT NULL DEFAULT '',
    target_language TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL,
    snippet TEXT NOT NULL,
    body_text TEXT NOT NULL DEFAULT '',
    attachment_names_json TEXT NOT NULL DEFAULT '[]',
    attachment_analysis TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    detailed_summary TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'Autre',
    tags_json TEXT NOT NULL DEFAULT '[]',
    priority TEXT NOT NULL,
    suggested_reply TEXT NOT NULL,
    should_reply INTEGER NOT NULL,
    draft_id TEXT,
    required_documents_json TEXT NOT NULL DEFAULT '[]',
    provided_documents_json TEXT NOT NULL DEFAULT '[]',
    approval_status TEXT NOT NULL DEFAULT 'pending',
    sent_message_id TEXT,
    telegram_notification_sent INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

ATTACHMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbound_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id TEXT NOT NULL,
    telegram_file_id TEXT NOT NULL,
    telegram_file_name TEXT NOT NULL,
    local_path TEXT NOT NULL,
    mime_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

UPDATES_SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id INTEGER PRIMARY KEY
);
"""

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS reply_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    sender TEXT,
    subject TEXT,
    email_body TEXT NOT NULL,
    final_reply TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(SCHEMA)
            connection.execute(ATTACHMENTS_SCHEMA)
            connection.execute(UPDATES_SCHEMA)
            connection.execute(MEMORY_SCHEMA)
            self._ensure_column(connection, "processed_emails", "required_documents_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "processed_emails", "provided_documents_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "processed_emails", "approval_status", "TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(connection, "processed_emails", "sent_message_id", "TEXT")
            self._ensure_column(connection, "processed_emails", "telegram_notification_sent", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "processed_emails", "reply_to", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "processed_emails", "internet_message_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "processed_emails", "telegram_ref", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "processed_emails", "target_language", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "processed_emails", "body_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "processed_emails", "attachment_names_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "processed_emails", "attachment_analysis", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "processed_emails", "detailed_summary", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "processed_emails", "category", "TEXT NOT NULL DEFAULT 'Autre'")
            self._ensure_column(connection, "processed_emails", "tags_json", "TEXT NOT NULL DEFAULT '[]'")
            connection.commit()

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing_names = {column[1] for column in columns}
        if column_name not in existing_names:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )

    def has_processed(self, gmail_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM processed_emails WHERE gmail_id = ?",
                (gmail_id,),
            ).fetchone()
        return row is not None

    def save_result(
        self,
        email: EmailMessage,
        analysis: EmailAnalysis,
        draft_id: str | None,
        telegram_ref: str,
        target_language: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO processed_emails (
                    gmail_id, thread_id, sender, reply_to, internet_message_id, telegram_ref, target_language,
                    subject, snippet, body_text, attachment_names_json, attachment_analysis, summary, detailed_summary, category, tags_json, priority, suggested_reply,
                    should_reply, draft_id, required_documents_json, provided_documents_json,
                    approval_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email.gmail_id,
                    email.thread_id,
                    email.sender,
                    email.reply_to,
                    email.internet_message_id,
                    telegram_ref,
                    target_language,
                    email.subject,
                    email.snippet,
                    email.body_text,
                    json.dumps(email.attachment_names, ensure_ascii=True),
                    analysis.attachment_analysis,
                    analysis.summary,
                    analysis.detailed_summary,
                    analysis.category,
                    json.dumps(analysis.tags, ensure_ascii=True),
                    analysis.priority,
                    analysis.suggested_reply,
                    int(analysis.should_reply),
                    draft_id,
                    json.dumps(analysis.required_documents, ensure_ascii=True),
                    json.dumps(analysis.provided_documents, ensure_ascii=True),
                    "pending",
                ),
            )
            connection.commit()

    def get_email_record(self, gmail_id: str) -> dict | None:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM processed_emails WHERE gmail_id = ?",
                (gmail_id,),
            ).fetchone()

        if row is None:
            return None

        record = dict(row)
        record["required_documents"] = json.loads(record["required_documents_json"] or "[]")
        record["provided_documents"] = json.loads(record["provided_documents_json"] or "[]")
        record["tags"] = json.loads(record.get("tags_json") or "[]")
        return record

    def resolve_gmail_id(self, short_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT gmail_id
                FROM processed_emails
                WHERE telegram_ref = ?
                ORDER BY processed_at DESC
                LIMIT 2
                """,
                (short_id[:3],),
            ).fetchall()

        if len(row) != 1:
            return None
        return row[0][0]

    def is_telegram_ref_available(self, telegram_ref: str, gmail_id: str | None = None) -> bool:
        with self._connect() as connection:
            if gmail_id:
                row = connection.execute(
                    """
                    SELECT 1
                    FROM processed_emails
                    WHERE telegram_ref = ? AND gmail_id != ?
                    LIMIT 1
                    """,
                    (telegram_ref, gmail_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT 1
                    FROM processed_emails
                    WHERE telegram_ref = ?
                    LIMIT 1
                    """,
                    (telegram_ref,),
                ).fetchone()
        return row is None

    def update_approval_status(
        self,
        gmail_id: str,
        status: str,
        sent_message_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE processed_emails
                SET approval_status = ?, sent_message_id = COALESCE(?, sent_message_id)
                WHERE gmail_id = ?
                """,
                (status, sent_message_id, gmail_id),
            )
            connection.commit()

    def mark_notification_sent(self, gmail_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE processed_emails SET telegram_notification_sent = 1 WHERE gmail_id = ?",
                (gmail_id,),
            )
            connection.commit()

    def update_suggested_reply(self, gmail_id: str, suggested_reply: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE processed_emails SET suggested_reply = ? WHERE gmail_id = ?",
                (suggested_reply, gmail_id),
            )
            connection.commit()

    def add_outbound_attachment(
        self,
        gmail_id: str,
        telegram_file_id: str,
        telegram_file_name: str,
        local_path: str,
        mime_type: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO outbound_attachments (
                    gmail_id, telegram_file_id, telegram_file_name, local_path, mime_type
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (gmail_id, telegram_file_id, telegram_file_name, local_path, mime_type),
            )
            connection.commit()

    def list_outbound_attachments(self, gmail_id: str) -> list[dict]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT gmail_id, telegram_file_id, telegram_file_name, local_path, mime_type
                FROM outbound_attachments
                WHERE gmail_id = ?
                ORDER BY id ASC
                """,
                (gmail_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def is_update_processed(self, update_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM telegram_updates WHERE update_id = ?",
                (update_id,),
            ).fetchone()
        return row is not None

    def mark_update_processed(self, update_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO telegram_updates (update_id) VALUES (?)",
                (update_id,),
            )
            connection.commit()

    def save_reply_memory(
        self,
        category: str,
        tags: list[str],
        sender: str,
        subject: str,
        email_body: str,
        final_reply: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reply_memory (
                    category, tags_json, sender, subject, email_body, final_reply
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    category,
                    json.dumps(tags, ensure_ascii=True),
                    sender,
                    subject,
                    email_body,
                    final_reply,
                ),
            )
            connection.commit()

    def list_reply_memory(
        self,
        category: str,
        tags: list[str],
        limit: int = 3,
    ) -> list[dict]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT category, tags_json, sender, subject, email_body, final_reply
                FROM reply_memory
                WHERE category = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (category, limit * 3),
            ).fetchall()

        wanted_tags = set(tags)
        results: list[dict] = []
        for row in rows:
            record = dict(row)
            record["tags"] = json.loads(record.get("tags_json") or "[]")
            if wanted_tags:
                overlap = wanted_tags.intersection(record["tags"])
                if not overlap and results:
                    continue
            results.append(record)
            if len(results) >= limit:
                break

        return results
