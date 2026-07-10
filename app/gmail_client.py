from __future__ import annotations

import base64
import mimetypes
import os
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.models import EmailAttachment, EmailMessage


SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


class GmailClient:
    def __init__(self, credentials_path: Path, token_path: Path) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = self._build_service()

    def _build_service(self):
        creds = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            if os.getenv("GMAIL_ALLOW_INTERACTIVE_AUTH", "").strip().lower() != "true":
                raise RuntimeError(
                    "Jeton Gmail invalide ou absent. Regenere token.json en local "
                    "(GMAIL_ALLOW_INTERACTIVE_AUTH=true) puis mets a jour GMAIL_TOKEN_BASE64. "
                    "En production, le flux interactif est desactive."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
            print("Autorisation Google requise.")
            print("Ouvre l'URL qui va s'afficher dans ton navigateur, puis valide l'acces.")
            creds = flow.run_local_server(port=0, open_browser=False)

        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds)

    def list_message_ids(
        self,
        query: str,
        page_token: str | None = None,
        page_size: int = 100,
    ) -> tuple[list[str], str | None]:
        """Retourne une page d'identifiants de messages (du plus recent au plus ancien)
        et le jeton de page suivant (None s'il n'y en a plus)."""
        request = self.service.users().messages().list(
            userId="me",
            q=query,
            maxResults=page_size,
            pageToken=page_token,
        )
        response = request.execute()
        ids = [item["id"] for item in response.get("messages", [])]
        return ids, response.get("nextPageToken")

    def get_message(self, message_id: str, account_id: str = "default") -> EmailMessage:
        message = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        headers = self._extract_headers(message)
        subject = headers.get("Subject", "(sans objet)")
        sender = headers.get("From", "(expéditeur inconnu)")
        reply_to = headers.get("Reply-To", sender)
        internet_message_id = headers.get("Message-ID", "")
        body_text = self._extract_body_text(message.get("payload", {})).strip()
        snippet = message.get("snippet", "")
        attachments = self._extract_attachments(message.get("payload", {}))
        attachment_names = [attachment.filename for attachment in attachments]

        return EmailMessage(
            gmail_id=message["id"],
            thread_id=message["threadId"],
            subject=subject,
            sender=sender,
            snippet=snippet,
            body_text=body_text or snippet,
            attachment_names=attachment_names,
            reply_to=reply_to,
            internet_message_id=internet_message_id,
            attachments=attachments,
            account_id=account_id,
        )

    def send_reply(
        self,
        email: EmailMessage,
        reply_text: str,
        attachment_paths: list[str] | None = None,
    ) -> str:
        mime_message = self._build_reply_message(email, reply_text, attachment_paths or [])
        encoded_message = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("utf-8")

        sent_message = (
            self.service.users()
            .messages()
            .send(
                userId="me",
                body={
                    "threadId": email.thread_id,
                    "raw": encoded_message,
                },
            )
            .execute()
        )

        return sent_message["id"]

    def mark_as_read(self, message_id: str) -> None:
        (
            self.service.users()
            .messages()
            .modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            )
            .execute()
        )

    def download_attachment(
        self,
        message_id: str,
        attachment: EmailAttachment,
        destination: Path,
    ) -> Path:
        payload = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment.attachment_id)
            .execute()
        )
        data = payload.get("data")
        if not data:
            raise ValueError(f"Piece jointe introuvable: {attachment.filename}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(base64.urlsafe_b64decode(data.encode("utf-8")))
        return destination

    def _extract_headers(self, message: dict[str, Any]) -> dict[str, str]:
        headers = message.get("payload", {}).get("headers", [])
        return {header["name"]: header["value"] for header in headers}

    def _extract_body_text(self, payload: dict[str, Any]) -> str:
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data")
            return self._decode_base64(data)

        parts = payload.get("parts", [])
        for part in parts:
            text = self._extract_body_text(part)
            if text:
                return text

        data = payload.get("body", {}).get("data")
        return self._decode_base64(data)

    def _decode_base64(self, data: str | None) -> str:
        if not data:
            return ""
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")

    def _extract_attachments(self, payload: dict[str, Any]) -> list[EmailAttachment]:
        attachments: list[EmailAttachment] = []
        self._collect_attachments(payload, attachments)
        return attachments

    def _collect_attachments(self, payload: dict[str, Any], attachments: list[EmailAttachment]) -> None:
        filename = payload.get("filename")
        body = payload.get("body", {})
        if filename and body.get("attachmentId"):
            attachments.append(
                EmailAttachment(
                    filename=filename,
                    mime_type=payload.get("mimeType", "application/octet-stream"),
                    attachment_id=body["attachmentId"],
                    part_id=payload.get("partId", ""),
                )
            )

        for part in payload.get("parts", []):
            self._collect_attachments(part, attachments)

    def _reply_subject(self, subject: str) -> str:
        if subject.lower().startswith("re:"):
            return subject
        return f"Re: {subject}"

    def _build_reply_message(
        self,
        email: EmailMessage,
        reply_text: str,
        attachment_paths: list[str],
    ) -> MIMEMultipart:
        message = MIMEMultipart()
        message["to"] = email.reply_to
        message["subject"] = self._reply_subject(email.subject)
        if email.internet_message_id:
            message["In-Reply-To"] = email.internet_message_id
            message["References"] = email.internet_message_id

        message.attach(MIMEText(reply_text, "plain", "utf-8"))

        for attachment_path in attachment_paths:
            path = Path(attachment_path)
            mime_type, _ = mimetypes.guess_type(str(path))
            maintype, subtype = ("application", "octet-stream")
            if mime_type:
                maintype, subtype = mime_type.split("/", 1)

            with path.open("rb") as file_handle:
                payload = MIMEApplication(file_handle.read(), _subtype=subtype)
                payload.add_header("Content-Disposition", "attachment", filename=path.name)
                payload.add_header("Content-Type", f"{maintype}/{subtype}", name=path.name)
                message.attach(payload)

        return message
