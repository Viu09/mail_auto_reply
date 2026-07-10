from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    mime_type: str
    attachment_id: str
    part_id: str


@dataclass(frozen=True)
class EmailMessage:
    gmail_id: str
    thread_id: str
    subject: str
    sender: str
    snippet: str
    body_text: str
    attachment_names: list[str]
    reply_to: str
    internet_message_id: str
    attachments: list[EmailAttachment]
    account_id: str = "default"
    received_at: datetime | None = None


@dataclass(frozen=True)
class EmailAnalysis:
    summary: str
    priority: str
    suggested_reply: str
    should_reply: bool
    required_documents: list[str]
    provided_documents: list[str]
    attachment_analysis: str
    detailed_summary: str = ""
    category: str = "Autre"
    tags: list[str] = field(default_factory=list)
    target_language: str = ""
