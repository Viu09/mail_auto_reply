from __future__ import annotations

from pathlib import Path

import requests


class TelegramClient:
    MAX_MESSAGE_LENGTH = 4000

    def __init__(self, enabled: bool, bot_token: str, chat_id: str) -> None:
        self.enabled = enabled
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send_message(self, text: str) -> None:
        if not self.enabled:
            return

        if not self.bot_token or not self.chat_id:
            raise ValueError(
                "Telegram est active mais TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID est manquant."
            )

        chunks = self._build_paginated_chunks(text)

        for chunk in chunks:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": chunk,
                },
                timeout=15,
            )
            response.raise_for_status()

    def send_photo(self, photo_path: Path, caption: str | None = None) -> None:
        if not self.enabled:
            return

        with photo_path.open("rb") as photo_handle:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendPhoto",
                data={
                    "chat_id": self.chat_id,
                    "caption": (caption or "")[:1024],
                },
                files={"photo": photo_handle},
                timeout=30,
            )
        response.raise_for_status()

    def send_document(self, document_path: Path, caption: str | None = None) -> None:
        if not self.enabled:
            return

        with document_path.open("rb") as document_handle:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendDocument",
                data={
                    "chat_id": self.chat_id,
                    "caption": (caption or "")[:1024],
                },
                files={"document": document_handle},
                timeout=30,
            )
        response.raise_for_status()

    def get_updates(self, offset: int | None = None) -> list[dict]:
        if not self.enabled:
            return []

        params = {"timeout": 1}
        if offset is not None:
            params["offset"] = offset

        response = requests.get(
            f"https://api.telegram.org/bot{self.bot_token}/getUpdates",
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("result", [])

    def download_file(self, file_id: str, destination: Path) -> Path:
        if not self.enabled:
            raise ValueError("Telegram n'est pas active.")

        file_response = requests.get(
            f"https://api.telegram.org/bot{self.bot_token}/getFile",
            params={"file_id": file_id},
            timeout=15,
        )
        file_response.raise_for_status()
        file_payload = file_response.json()
        file_path = file_payload["result"]["file_path"]

        download_response = requests.get(
            f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}",
            timeout=30,
        )
        download_response.raise_for_status()

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(download_response.content)
        return destination

    def _build_paginated_chunks(self, text: str) -> list[str]:
        normalized = text.strip()
        if len(normalized) <= self.MAX_MESSAGE_LENGTH:
            return [normalized]

        base_chunks = self._split_message(normalized, self.MAX_MESSAGE_LENGTH - 20)
        paginated_chunks: list[str] = []
        total_chunks = len(base_chunks)

        for index, chunk in enumerate(base_chunks, start=1):
            prefix = f"Message {index}/{total_chunks}\n\n"
            available_length = self.MAX_MESSAGE_LENGTH - len(prefix)
            paginated_chunks.extend(
                self._paginate_with_prefix(prefix, chunk, available_length, index, total_chunks)
            )

        return paginated_chunks

    def _paginate_with_prefix(
        self,
        prefix: str,
        chunk: str,
        available_length: int,
        index: int,
        total_chunks: int,
    ) -> list[str]:
        if len(chunk) <= available_length:
            return [prefix + chunk]

        sub_chunks = self._split_message(chunk, available_length)
        return [f"Message {index}.{sub_index}/{total_chunks}\n\n{sub_chunk}" for sub_index, sub_chunk in enumerate(sub_chunks, start=1)]

    def _split_message(self, text: str, max_length: int) -> list[str]:
        if len(text) <= max_length:
            return [text]

        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = min(start + max_length, len(text))
            if end < len(text):
                split_at = text.rfind("\n\n", start, end)
                if split_at == -1:
                    split_at = text.rfind("\n", start, end)
                if split_at == -1 or split_at <= start:
                    split_at = end
            else:
                split_at = end

            chunk = text[start:split_at].strip()
            if chunk:
                chunks.append(chunk)

            start = split_at
            while start < len(text) and text[start] in {"\n", " "}:
                start += 1

        return chunks
