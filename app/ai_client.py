from __future__ import annotations

import json

from openai import OpenAI

from app.models import EmailAnalysis, EmailMessage


class AIClient:
    def __init__(self, api_key: str, model: str, reply_language: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.reply_language = reply_language

    def analyze_email(self, email: EmailMessage) -> EmailAnalysis:
        prompt = f"""
Tu analyses un email reçu et tu proposes une réponse.

Réponds uniquement en JSON avec cette structure exacte :
{{
  "summary": "string",
  "priority": "low | medium | high",
  "suggested_reply": "string",
  "should_reply": true,
  "required_documents": ["string"],
  "provided_documents": ["string"]
}}

Règles :
- Le résumé doit faire 3 lignes maximum.
- Le résumé doit etre precis et mentionner clairement l'action attendue.
- La réponse proposée doit être concise, naturelle, professionnelle et directement exploitable.
- La réponse doit être rédigée en langue : {self.reply_language}
- Si l'email est publicitaire, automatique ou n'appelle pas de réponse, mets "should_reply" à false.
- "required_documents" doit lister les documents explicitement demandes dans l'email.
- "provided_documents" doit lister les documents ou pieces jointes deja fournis dans l'email.
- Si rien n'est demande ou fourni, renvoie une liste vide.

Email :
From: {email.sender}
Subject: {email.subject}
Snippet: {email.snippet}
Attachment names: {", ".join(email.attachment_names) if email.attachment_names else "none"}
Body:
{email.body_text}
""".strip()

        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": "Tu es un assistant email fiable. Tu renvoies uniquement du JSON valide.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            text={"format": {"type": "json_object"}},
        )

        payload = json.loads(response.output_text)

        return EmailAnalysis(
            summary=payload["summary"].strip(),
            priority=payload["priority"].strip(),
            suggested_reply=payload["suggested_reply"].strip(),
            should_reply=bool(payload["should_reply"]),
            required_documents=[item.strip() for item in payload.get("required_documents", []) if item.strip()],
            provided_documents=[item.strip() for item in payload.get("provided_documents", []) if item.strip()],
            attachment_analysis="",
        )
