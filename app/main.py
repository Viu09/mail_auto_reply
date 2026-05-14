from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

from PyPDF2 import PdfReader
from docx import Document

from app.advanced_ai_client import AIClient
from app.config import get_settings
from app.db import Database
from app.gmail_client import GmailClient
from app.models import EmailAnalysis, EmailMessage
from app.notifier import Notifier
from app.telegram_client import TelegramClient


def process_once() -> None:
    settings = get_settings()
    database = Database(settings.database_path)
    gmail = GmailClient(settings.gmail_credentials_path, settings.gmail_token_path)
    ai = AIClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        reply_language=settings.default_reply_language,
    )
    notifier = Notifier(enabled=settings.enable_desktop_notifications)
    telegram = TelegramClient(
        enabled=settings.enable_telegram_notifications,
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )

    message_ids = gmail.list_unprocessed_messages(settings.gmail_query)

    if not message_ids:
        print("Aucun nouvel email a traiter.")

    for message_id in message_ids:
        if database.has_processed(message_id):
            continue

        email = gmail.get_message(message_id)
        analysis = ai.analyze_email(email)
        target_language = detect_email_language(ai, email)
        attachment_analysis = analyze_incoming_attachments(gmail, ai, email, target_language)
        analysis = adapt_analysis_to_email_language(ai, email, analysis, target_language)
        analysis = enrich_analysis_with_attachment_context(
            ai,
            email,
            analysis,
            target_language,
            attachment_analysis,
        )
        analysis = enforce_external_resource_awareness(ai, email, analysis, target_language)
        analysis = adapt_analysis_with_memory(database, ai, email, analysis, target_language)
        analysis = enforce_bailiff_collection_style(ai, email, analysis, target_language)
        analysis = enforce_detailed_summary_format(ai, email, analysis, target_language)
        analysis = enforce_telegram_summary_format(ai, email, analysis, target_language)

        notifier.notify(
            title=f"Nouveau mail: {email.subject}",
            message=f"{email.sender}\n{analysis.summary}",
        )
        telegram.send_message(
            "\n".join(
                [
                    f"Nouveau mail de {email.sender}",
                    f"Sujet : {email.subject}",
                    f"Priorite : {analysis.priority}",
                    "",
                    "Resume :",
                    analysis.summary,
                    "",
                    "Reponse proposee :",
                    analysis.suggested_reply or "(aucune)",
                ]
            )
        )

        draft_id = None
        short_id = build_short_reference(database, email.gmail_id)
        database.save_result(email, analysis, draft_id, short_id, target_language)
        gmail.mark_as_read(message_id)

        telegram.send_message(build_telegram_summary(email, analysis, short_id))
        send_incoming_attachment_previews(gmail, telegram, email, short_id)
        database.mark_notification_sent(email.gmail_id)

        print("=" * 72)
        print(f"From: {email.sender}")
        print(f"Subject: {email.subject}")
        print(f"Priority: {analysis.priority}")
        print("Summary:")
        print(analysis.summary)
        print(f"Reference Telegram: {short_id}")

    process_telegram_updates(database, gmail, ai, telegram)


def process_telegram_updates(
    database: Database,
    gmail: GmailClient,
    ai: AIClient,
    telegram: TelegramClient,
) -> None:
    if not telegram.enabled:
        return

    updates = telegram.get_updates()
    for update in updates:
        update_id = update.get("update_id")
        if update_id is None or database.is_update_processed(update_id):
            continue

        try:
            handle_telegram_update(database, gmail, ai, telegram, update)
        finally:
            database.mark_update_processed(update_id)


def handle_telegram_update(
    database: Database,
    gmail: GmailClient,
    ai: AIClient,
    telegram: TelegramClient,
    update: dict,
) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    text = (message.get("text") or "").strip()
    if text:
        handle_telegram_text(database, gmail, ai, telegram, text)
        return

    document = message.get("document")
    photo_sizes = message.get("photo") or []
    caption = (message.get("caption") or "").strip()
    if document and caption:
        handle_telegram_document(database, telegram, document, caption)
    elif photo_sizes and caption:
        handle_telegram_photo(database, telegram, photo_sizes, caption)


def handle_telegram_text(
    database: Database,
    gmail: GmailClient,
    ai: AIClient,
    telegram: TelegramClient,
    text: str,
) -> None:
    normalized = text.strip()
    upper_text = normalized.upper()

    if upper_text in {"/START", "/HELP"}:
        telegram.send_message(
            "Commandes disponibles:\n"
            "- OK <reference> : envoie la reponse par email\n"
            "- NON <reference> : annule la reponse\n"
            "- EDIT <reference> <consignes> : retravaille la reponse avec OpenAI\n"
            "- FULL <reference> : affiche le contenu integral du mail\n"
            "- DETAILS <reference> : affiche la synthese detaillee du mail\n"
            "- DOCS <reference> : affiche l'analyse detaillee des pieces jointes\n"
            "- ATTACH <reference> en legende d'un document Telegram : ajoute une piece jointe"
        )
        return

    if upper_text.startswith("FULL "):
        handle_telegram_full(database, telegram, normalized)
        return

    if upper_text.startswith("DETAILS "):
        handle_telegram_details(database, telegram, normalized)
        return

    if upper_text.startswith("DOCS "):
        handle_telegram_docs(database, telegram, normalized)
        return

    if upper_text.startswith("EDIT "):
        handle_telegram_edit(database, ai, telegram, normalized)
        return

    parts = normalized.split(maxsplit=1)
    if len(parts) != 2:
        return

    command, reference = parts[0].upper(), parts[1].strip()
    gmail_id = database.resolve_gmail_id(reference)
    if not gmail_id:
        telegram.send_message(
            f"Reference introuvable ou ambigue: {reference}. Utilise les 8 premiers caracteres envoyes dans la notification."
        )
        return

    record = database.get_email_record(gmail_id)
    if not record:
        telegram.send_message("Email introuvable en base.")
        return

    if command == "NON":
        database.update_approval_status(gmail_id, "rejected")
        telegram.send_message(f"Reponse annulee pour {reference}.")
        return

    if command != "OK":
        return

    if record["approval_status"] == "sent":
        telegram.send_message(f"La reponse pour {reference} a deja ete envoyee.")
        return

    email = EmailMessage(
        gmail_id=record["gmail_id"],
        thread_id=record["thread_id"],
        subject=record["subject"],
        sender=record["sender"],
        snippet=record["snippet"],
        body_text=record.get("body_text") or "",
        attachment_names=json.loads(record.get("attachment_names_json") or "[]"),
        reply_to=record.get("reply_to") or record["sender"],
        internet_message_id=record.get("internet_message_id") or "",
        attachments=[],
    )
    target_language = record.get("target_language") or detect_email_language(ai, email)
    normalized_reply = rewrite_reply_in_language(
        ai,
        email,
        normalize_reply_text(record["suggested_reply"]),
        target_language,
    )
    normalized_reply = ensure_email_signature(normalized_reply)
    attachment_paths = [item["local_path"] for item in database.list_outbound_attachments(gmail_id)]
    sent_message_id = gmail.send_reply(email, normalized_reply, attachment_paths)
    database.update_approval_status(gmail_id, "sent", sent_message_id)
    database.save_reply_memory(
        category=record.get("category") or "Autre",
        tags=record.get("tags") or [],
        sender=record.get("sender") or "",
        subject=record.get("subject") or "",
        email_body=record.get("body_text") or "",
        final_reply=normalized_reply,
    )
    telegram.send_message(
        "Reponse envoyee.\n"
        f"Reference: {reference}\n"
        f"Pieces jointes envoyees: {len(attachment_paths)}"
    )


def handle_telegram_document(
    database: Database,
    telegram: TelegramClient,
    document: dict,
    caption: str,
) -> None:
    parts = caption.split(maxsplit=1)
    if len(parts) != 2 or parts[0].upper() != "ATTACH":
        return

    reference = parts[1].strip()
    gmail_id = database.resolve_gmail_id(reference)
    if not gmail_id:
        telegram.send_message(f"Reference introuvable ou ambigue: {reference}.")
        return

    file_name = document.get("file_name") or f"{document['file_id']}.bin"
    destination = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "outbound_attachments"
        / gmail_id
        / file_name
    )
    telegram.download_file(document["file_id"], destination)
    database.add_outbound_attachment(
        gmail_id=gmail_id,
        telegram_file_id=document["file_id"],
        telegram_file_name=file_name,
        local_path=str(destination),
        mime_type=document.get("mime_type"),
    )
    telegram.send_message(
        f"Piece jointe ajoutee pour {reference}: {file_name}\n"
        "Tu peux maintenant envoyer `OK <reference>` pour valider l'envoi."
    )


def handle_telegram_photo(
    database: Database,
    telegram: TelegramClient,
    photo_sizes: list[dict],
    caption: str,
) -> None:
    parts = caption.split(maxsplit=1)
    if len(parts) != 2 or parts[0].upper() != "ATTACH":
        return

    reference = parts[1].strip()
    gmail_id = database.resolve_gmail_id(reference)
    if not gmail_id:
        telegram.send_message(f"Reference introuvable ou ambigue: {reference}.")
        return

    best_photo = photo_sizes[-1]
    file_id = best_photo["file_id"]
    file_name = f"{file_id}.jpg"
    destination = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "outbound_attachments"
        / gmail_id
        / file_name
    )
    telegram.download_file(file_id, destination)
    database.add_outbound_attachment(
        gmail_id=gmail_id,
        telegram_file_id=file_id,
        telegram_file_name=file_name,
        local_path=str(destination),
        mime_type="image/jpeg",
    )
    telegram.send_message(
        f"Photo ajoutee pour {reference}: {file_name}\n"
        "Tu peux maintenant envoyer `OK <reference>` pour valider l'envoi."
    )


def handle_telegram_edit(
    database: Database,
    ai: AIClient,
    telegram: TelegramClient,
    text: str,
) -> None:
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        telegram.send_message("Format attendu: EDIT <reference> <consignes>")
        return

    _, reference, instructions = parts
    gmail_id = database.resolve_gmail_id(reference)
    if not gmail_id:
        telegram.send_message(f"Reference introuvable ou ambigue: {reference}.")
        return

    record = database.get_email_record(gmail_id)
    if not record:
        telegram.send_message("Email introuvable en base.")
        return

    email = EmailMessage(
        gmail_id=record["gmail_id"],
        thread_id=record["thread_id"],
        subject=record["subject"],
        sender=record["sender"],
        snippet=record["snippet"],
        body_text=record.get("body_text") or "",
        attachment_names=json.loads(record.get("attachment_names_json") or "[]"),
        reply_to=record.get("reply_to") or record["sender"],
        internet_message_id=record.get("internet_message_id") or "",
        attachments=[],
    )
    target_language = record.get("target_language") or detect_email_language(ai, email)
    refined_reply = refine_reply_with_ai(
        ai,
        email,
        record["suggested_reply"],
        instructions,
        target_language,
        record.get("attachment_analysis") or "",
    )
    database.update_suggested_reply(gmail_id, refined_reply)
    telegram.send_message(
        f"Reponse mise a jour pour {reference}.\n\nNouvelle reponse proposee:\n{refined_reply}"
    )


def handle_telegram_docs(
    database: Database,
    telegram: TelegramClient,
    text: str,
) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        telegram.send_message("Format attendu: DOCS <reference>")
        return

    reference = parts[1].strip()
    gmail_id = database.resolve_gmail_id(reference)
    if not gmail_id:
        telegram.send_message(f"Reference introuvable ou ambigue: {reference}.")
        return

    record = database.get_email_record(gmail_id)
    if not record:
        telegram.send_message("Email introuvable en base.")
        return

    telegram.send_message(
        f"Analyse detaillee des pieces jointes pour {reference}:\n\n"
        f"{record.get('attachment_analysis') or 'Aucune analyse disponible.'}"
    )


def handle_telegram_details(
    database: Database,
    telegram: TelegramClient,
    text: str,
) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        telegram.send_message("Format attendu: DETAILS <reference>")
        return

    reference = parts[1].strip()
    gmail_id = database.resolve_gmail_id(reference)
    if not gmail_id:
        telegram.send_message(f"Reference introuvable ou ambigue: {reference}.")
        return

    record = database.get_email_record(gmail_id)
    if not record:
        telegram.send_message("Email introuvable en base.")
        return

    detailed_summary = record.get("detailed_summary") or record.get("summary") or "Aucune synthese disponible."
    telegram.send_message(
        f"Synthese detaillee pour {reference}:\n\n{detailed_summary}"
    )


def handle_telegram_full(
    database: Database,
    telegram: TelegramClient,
    text: str,
) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        telegram.send_message("Format attendu: FULL <reference>")
        return

    reference = parts[1].strip()
    gmail_id = database.resolve_gmail_id(reference)
    if not gmail_id:
        telegram.send_message(f"Reference introuvable ou ambigue: {reference}.")
        return

    record = database.get_email_record(gmail_id)
    if not record:
        telegram.send_message("Email introuvable en base.")
        return

    telegram.send_message(
        f"Contenu integral du mail {reference}:\n\n"
        f"Sujet: {record.get('subject') or '(sans objet)'}\n"
        f"De: {record.get('sender') or '(expediteur inconnu)'}\n\n"
        f"{record.get('body_text') or record.get('snippet') or '(contenu indisponible)'}"
    )


def build_telegram_summary(email: EmailMessage, analysis, short_id: str) -> str:
    category = getattr(analysis, "category", "Autre").upper()
    tags = getattr(analysis, "tags", []) or []
    external_resources = extract_external_resource_references(email.body_text)
    required_documents = (
        "\n".join(f"- {item}" for item in analysis.required_documents)
        if analysis.required_documents
        else "- Aucun document demande"
    )
    provided_documents = (
        "\n".join(f"- {item}" for item in analysis.provided_documents)
        if analysis.provided_documents
        else "- Aucun document detecte"
    )
    attachments_in_mail = (
        "\n".join(f"- {item}" for item in email.attachment_names)
        if email.attachment_names
        else "- Aucune piece jointe dans le mail"
    )
    external_resources_text = (
        "\n".join(f"- {item}" for item in external_resources)
        if external_resources
        else "- Aucune ressource externe mentionnee"
    )

    tags_line = f"Tags: {', '.join(tags)}\n" if tags else ""

    return (
        f"【{category}】 Nouvel email [{short_id}]\n"
        f"{tags_line}"
        f"De: {email.sender}\n"
        f"Sujet: {email.subject}\n"
        f"Priorite: {analysis.priority}\n\n"
        f"Resume:\n{analysis.summary}\n\n"
        f"Documents a fournir:\n{required_documents}\n\n"
        f"Documents fournis dans le mail:\n{provided_documents}\n\n"
        f"Pieces jointes recues:\n{attachments_in_mail}\n\n"
        f"Ressources externes mentionnees:\n{external_resources_text}\n\n"
        f"Reponse proposee:\n{analysis.suggested_reply}\n\n"
        f"Actions:\n"
        f"- envoie `OK {short_id}` pour envoyer la reponse\n"
        f"- envoie `NON {short_id}` pour annuler\n"
        f"- envoie `EDIT {short_id} <consignes>` pour ajuster la reponse\n"
        f"- envoie `FULL {short_id}` pour lire le mail complet\n"
        f"- envoie `DETAILS {short_id}` pour voir la synthese detaillee du mail\n"
        f"- envoie `DOCS {short_id}` pour voir l'analyse detaillee des pieces jointes\n"
        f"- envoie un document Telegram avec la legende `ATTACH {short_id}` pour l'ajouter au mail"
    )


def build_short_reference(database: Database, gmail_id: str) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    seed = sum((index + 1) * ord(char) for index, char in enumerate(gmail_id))

    for attempt in range(len(alphabet) ** 3):
        value = (seed + attempt) % (len(alphabet) ** 3)
        chars: list[str] = []
        for _ in range(3):
            chars.append(alphabet[value % len(alphabet)])
            value //= len(alphabet)
        reference = "".join(reversed(chars))
        if database.is_telegram_ref_available(reference, gmail_id=gmail_id):
            return reference

    return gmail_id[:3].upper()


def normalize_reply_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    blocks: list[str] = []
    for block in cleaned.split("\n\n"):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        is_list = all(
            line.startswith("- ")
            or line.startswith("* ")
            or re.match(r"^\d+\.\s", line)
            for line in lines
        )

        if is_list:
            blocks.append("\n".join(lines))
        else:
            blocks.append(" ".join(lines))

    return "\n\n".join(blocks)


def send_incoming_attachment_previews(
    gmail: GmailClient,
    telegram: TelegramClient,
    email: EmailMessage,
    short_id: str,
) -> None:
    if not telegram.enabled or not email.attachments:
        return

    base_dir = Path(__file__).resolve().parent.parent / "data" / "incoming_attachments" / email.gmail_id
    for attachment in email.attachments:
        destination = base_dir / attachment.filename
        try:
            if not destination.exists():
                gmail.download_attachment(email.gmail_id, attachment, destination)
            if attachment.mime_type.startswith("image/"):
                telegram.send_photo(destination, caption=f"Piece jointe recue [{short_id}] : {attachment.filename}")
            else:
                telegram.send_document(destination, caption=f"Piece jointe recue [{short_id}] : {attachment.filename}")
        except Exception as exc:
            telegram.send_message(
                f"Impossible d'envoyer l'aperçu de la piece jointe {attachment.filename}: {exc}"
            )


def refine_reply_with_ai(
    ai: AIClient,
    email: EmailMessage,
    current_reply: str,
    instructions: str,
    target_language: str,
    attachment_analysis: str,
) -> str:
    prompt = f"""
    Tu dois retravailler une reponse email professionnelle.

    Regles :
    - Garde le fond utile de la reponse existante.
    - Integre les consignes de l'utilisateur, meme si elles sont ecrites dans une autre langue.
    - Detecte la langue principale de l'email recu.
    - Redige l'email final uniquement dans cette langue cible : {target_language}.
    - Prends en compte tous les elements disponibles : message, pieces jointes, documents demandes et documents effectivement fournis.
    - Si un document est annonce comme fourni mais n'est pas detecte dans les elements disponibles, signale-le poliment.
    - La reponse doit etre cordiale, precise, professionnelle et respecter les standards d'un vrai corps d'email.
    - Termine toujours par la signature exacte : Samo Ferman
    - Ne coupe jamais les phrases avec des retours a la ligne.
    - Utilise des paragraphes courts et propres.
    - Retourne uniquement le texte final de l'email.

Email recu :
From: {email.sender}
Subject: {email.subject}
    Body:
    {email.body_text}

    Analyse des pieces jointes :
    {attachment_analysis or "Aucune analyse complementaire"}

    Reponse actuelle :
{current_reply}

Consignes utilisateur :
{instructions}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
    )
    return ensure_email_signature(normalize_reply_text(response.output_text))


def adapt_analysis_to_email_language(
    ai: AIClient,
    email: EmailMessage,
    analysis,
    language: str,
):
    rewritten_reply = rewrite_reply_in_language(ai, email, analysis.suggested_reply, language)

    return type(analysis)(
        summary=analysis.summary,
        detailed_summary=getattr(analysis, "detailed_summary", analysis.summary),
        priority=analysis.priority,
        suggested_reply=ensure_email_signature(rewritten_reply),
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=getattr(analysis, "attachment_analysis", ""),
        category=getattr(analysis, "category", "Autre"),
        tags=getattr(analysis, "tags", []),
    )


def enrich_analysis_with_attachment_context(
    ai: AIClient,
    email: EmailMessage,
    analysis: EmailAnalysis,
    target_language: str,
    attachment_analysis: str,
) -> EmailAnalysis:
    discrepancy_note = build_attachment_discrepancy_note(email, analysis)

    if not attachment_analysis.strip():
        base_analysis = EmailAnalysis(
            summary=analysis.summary,
            detailed_summary=getattr(analysis, "detailed_summary", analysis.summary),
            priority=analysis.priority,
            suggested_reply=analysis.suggested_reply,
            should_reply=analysis.should_reply,
            required_documents=analysis.required_documents,
            provided_documents=analysis.provided_documents,
            attachment_analysis="",
            category=getattr(analysis, "category", "Autre"),
            tags=getattr(analysis, "tags", []),
        )
        return enforce_attachment_consistency(ai, email, base_analysis, target_language, discrepancy_note)

    prompt = f"""
Tu dois ameliorer l'analyse d'un email a partir du message et de l'analyse de ses pieces jointes.

Retourne uniquement un JSON valide avec cette structure :
{{
  "summary": "string",
  "detailed_summary": "string",
  "suggested_reply": "string"
}}

Regles :
- Le resume doit etre precis, exploitable et tenir en 3 lignes maximum.
- La reponse doit etre plus pertinente grace au contenu des pieces jointes.
- La reponse doit etre redigee en {target_language}.
- La reponse doit tenir compte du message, des pieces jointes, des documents mentionnes comme fournis et de ceux reellement presents.
- Si un document est annonce comme fourni mais n'est pas detecte dans les pieces jointes ou leur contenu, la reponse doit le mentionner poliment.
- La reponse doit etre cordiale, precise, professionnelle et conforme aux standards d'un email.
- Termine toujours la reponse par la signature exacte : Samo Ferman
- Ne coupe pas les phrases avec des retours a la ligne.

Email :
From: {email.sender}
Subject: {email.subject}
Body:
{email.body_text}

Analyse actuelle :
Resume: {analysis.summary}
Synthese detaillee: {getattr(analysis, "detailed_summary", analysis.summary)}
Reponse: {analysis.suggested_reply}

Incoherences detectees :
{discrepancy_note or "Aucune incoherence detectee"}

Analyse des pieces jointes :
{attachment_analysis}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    payload = json.loads(response.output_text)

    enriched = EmailAnalysis(
        summary=payload.get("summary", analysis.summary).strip() or analysis.summary,
        priority=analysis.priority,
        suggested_reply=ensure_email_signature(
            normalize_reply_text(payload.get("suggested_reply", analysis.suggested_reply))
        ),
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=attachment_analysis,
        category=getattr(analysis, "category", "Autre"),
        tags=getattr(analysis, "tags", []),
    )
    return enforce_attachment_consistency(ai, email, enriched, target_language, discrepancy_note)


def detect_email_language(ai: AIClient, email: EmailMessage) -> str:
    prompt = f"""
Determine la langue principale de cet email.
Reponds avec uniquement le nom de la langue en anglais, par exemple:
French
English
Spanish
German
Italian

Email:
Subject: {email.subject}
Body:
{email.body_text}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
    )
    return response.output_text.strip() or "English"


def rewrite_reply_in_language(
    ai: AIClient,
    email: EmailMessage,
    reply_text: str,
    language: str,
) -> str:
    prompt = f"""
Rewrite this email reply in {language}.

Rules:
- Keep the meaning and level of professionalism.
- Use natural business email phrasing.
- If the source text contains mixed languages, translate everything to {language}.
- Make the reply cordial, precise, and aligned with professional email standards.
- End the email with the exact signature: Samo Ferman
- Keep clean paragraphs.
- Do not insert arbitrary line breaks inside sentences.
- Return only the final email text.

Incoming email:
Subject: {email.subject}
Body:
{email.body_text}

Reply draft:
{reply_text}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
    )
    return ensure_email_signature(normalize_reply_text(response.output_text))


def analyze_incoming_attachments(
    gmail: GmailClient,
    ai: AIClient,
    email: EmailMessage,
    target_language: str,
) -> str:
    if not email.attachments:
        return ""

    base_dir = Path(__file__).resolve().parent.parent / "data" / "incoming_attachments" / email.gmail_id
    reports: list[str] = []

    for attachment in email.attachments:
        destination = base_dir / attachment.filename
        try:
            if not destination.exists():
                gmail.download_attachment(email.gmail_id, attachment, destination)
            report = analyze_single_attachment(ai, destination, attachment.mime_type, target_language)
            if report:
                reports.append(f"{attachment.filename}: {report}")
        except Exception as exc:
            reports.append(f"{attachment.filename}: analyse impossible ({exc})")

    return "\n".join(f"- {item}" for item in reports)


def analyze_single_attachment(
    ai: AIClient,
    path: Path,
    mime_type: str,
    target_language: str,
) -> str:
    if mime_type.startswith("image/"):
        return analyze_image_attachment(ai, path, mime_type, target_language)

    extracted_text = extract_text_from_attachment(path, mime_type)
    if extracted_text:
        return summarize_attachment_text(ai, path.name, extracted_text, target_language)

    return "contenu non exploitable automatiquement"


def analyze_image_attachment(
    ai: AIClient,
    path: Path,
    mime_type: str,
    target_language: str,
) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    response = ai.client.responses.create(
        model=ai.model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f"Analyse cette image et fais un compte rendu utile en {target_language}. "
                            "Identifie les informations importantes pour comprendre le mail et preparer une reponse professionnelle. "
                            "Reste concis mais precis."
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{encoded}",
                    },
                ],
            }
        ],
    )
    return normalize_reply_text(response.output_text)


def extract_text_from_attachment(path: Path, mime_type: str) -> str:
    suffix = path.suffix.lower()

    if mime_type.startswith("text/") or suffix in {".txt", ".csv", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")[:20000]

    if suffix == ".pdf":
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text[:20000]

    if suffix == ".docx":
        document = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return text[:20000]

    return ""


def summarize_attachment_text(
    ai: AIClient,
    filename: str,
    text: str,
    target_language: str,
) -> str:
    prompt = f"""
Analyse le contenu de ce document et fais un compte rendu utile en {target_language}.

Regles :
- Resume le document de facon concise et precise.
- Fais ressortir les informations utiles pour comprendre le mail.
- Signale les informations qui peuvent aider a construire la reponse.
- Retourne uniquement le compte rendu final.

Nom du fichier : {filename}

Contenu :
{text}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
    )
    return normalize_reply_text(response.output_text)


def build_attachment_discrepancy_note(email: EmailMessage, analysis: EmailAnalysis) -> str:
    claimed_documents = analysis.provided_documents
    actual_attachments = email.attachment_names
    attachment_claim = email_explicitly_claims_attachments(email.body_text)

    if claimed_documents and attachment_claim and not actual_attachments:
        return (
            "Le corps du mail affirme que des documents sont fournis, "
            "mais aucune piece jointe n'a ete recue dans l'email."
        )

    if claimed_documents and attachment_claim and actual_attachments and len(actual_attachments) < len(claimed_documents):
        return (
            "Le mail mentionne plus de documents fournis que le nombre de pieces jointes reellement recues. "
            "Il peut manquer un ou plusieurs fichiers."
        )

    return ""


def enforce_attachment_consistency(
    ai: AIClient,
    email: EmailMessage,
    analysis: EmailAnalysis,
    target_language: str,
    discrepancy_note: str,
) -> EmailAnalysis:
    if not discrepancy_note:
        return analysis

    prompt = f"""
Tu corriges une proposition de reponse email pour qu'elle soit factuellement correcte.

Regles :
- Redige en {target_language}.
- N'affirme jamais avoir recu des documents ou pieces jointes si ce n'est pas le cas.
- Si le mail mentionne des documents supposes joints mais qu'ils sont absents, signale-le poliment et clairement.
- Conserve un ton cordial, professionnel, precis et naturel.
- Termine par la signature exacte : Samo Ferman
- Retourne uniquement un JSON valide avec :
{{
  "summary": "string",
  "suggested_reply": "string"
}}

Email recu :
From: {email.sender}
Subject: {email.subject}
Body:
{email.body_text}

Resume actuel :
{analysis.summary}

Reponse actuelle :
{analysis.suggested_reply}

Incoherence a corriger :
{discrepancy_note}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    payload = json.loads(response.output_text)

    return EmailAnalysis(
        summary=(payload.get("summary") or analysis.summary).strip(),
        priority=analysis.priority,
        suggested_reply=ensure_email_signature(
            normalize_reply_text(payload.get("suggested_reply", analysis.suggested_reply))
        ),
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=analysis.attachment_analysis,
        category=getattr(analysis, "category", "Autre"),
    )


def ensure_email_signature(text: str) -> str:
    normalized = text.strip()
    if normalized.endswith("Samo Ferman"):
        return normalized
    return f"{normalized}\n\nSamo Ferman"


def extract_external_resource_references(body_text: str) -> list[str]:
    references: list[str] = []

    if re.search(r"instagram", body_text, re.IGNORECASE):
        handles = re.findall(r"@[\w\.\-]+", body_text)
        if handles:
            for handle in handles:
                references.append(f"Instagram {handle}")
        else:
            references.append("Page Instagram mentionnee")

    for url in re.findall(r"https?://\S+", body_text):
        cleaned = url.rstrip(").,;")
        references.append(cleaned)

    unique_references: list[str] = []
    seen: set[str] = set()
    for item in references:
        if item not in seen:
            seen.add(item)
            unique_references.append(item)

    return unique_references


def email_explicitly_claims_attachments(body_text: str) -> bool:
    patterns = [
        r"pi[eè]ce(?:s)? jointe(?:s)?",
        r"ci[- ]joint(?:e)?s?",
        r"vous trouverez en pi[eè]ce jointe",
        r"en annexe",
    ]
    return any(re.search(pattern, body_text, re.IGNORECASE) for pattern in patterns)


def enforce_external_resource_awareness(
    ai: AIClient,
    email: EmailMessage,
    analysis: EmailAnalysis,
    target_language: str,
) -> EmailAnalysis:
    external_resources = extract_external_resource_references(email.body_text)
    if not external_resources:
        return analysis

    if email_explicitly_claims_attachments(email.body_text):
        return analysis

    current_tags = [tag for tag in getattr(analysis, "tags", []) if tag != "PieceJointeManquante"]
    prompt = f"""
Tu corriges une analyse d'email pour tenir compte de ressources externes mentionnees dans le message.

Retourne uniquement un JSON valide avec cette structure :
{{
  "summary": "string",
  "detailed_summary": "string",
  "suggested_reply": "string"
}}

Regles :
- Redige en {target_language}.
- Le mail mentionne des ressources externes disponibles, pas des pieces jointes necessairement envoyees.
- N'ecris donc pas que les photos ou videos sont manquantes en piece jointe si elles sont seulement referencees sur une page externe.
- Mentionne explicitement les ressources externes pertinentes.
- La reponse doit rester precise, professionnelle, utile et coherente.

Email :
Subject: {email.subject}
Body:
{email.body_text}

Ressources externes detectees :
{", ".join(external_resources)}

Analyse actuelle :
Resume: {analysis.summary}
Synthese detaillee: {analysis.detailed_summary or analysis.summary}
Reponse: {analysis.suggested_reply}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    payload = json.loads(response.output_text)

    return EmailAnalysis(
        summary=(payload.get("summary") or analysis.summary).strip(),
        priority=analysis.priority,
        suggested_reply=ensure_email_signature(
            normalize_reply_text(payload.get("suggested_reply", analysis.suggested_reply))
        ),
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=analysis.attachment_analysis,
        detailed_summary=(payload.get("detailed_summary") or analysis.detailed_summary or analysis.summary).strip(),
        category=getattr(analysis, "category", "Autre"),
        tags=current_tags,
    )


def enforce_bailiff_collection_style(
    ai: AIClient,
    email: EmailMessage,
    analysis: EmailAnalysis,
    target_language: str,
) -> EmailAnalysis:
    category = getattr(analysis, "category", "Autre")
    tags_list = getattr(analysis, "tags", []) or []
    tags = set(tags_list)
    is_collection_context = category == "Huissier" or bool(
        tags.intersection({"Contentieux", "MiseEnDemeure", "Procedure", "Impaye"})
    )

    if not is_collection_context:
        return analysis

    prompt = f"""
Tu rediges une version plus aboutie, plus polie et plus detaillee d'une reponse email dans un contexte d'huissier ou de recouvrement.

Retourne uniquement un JSON valide avec cette structure :
{{
  "suggested_reply": "string"
}}

Contraintes absolues :
- Redige en {target_language}.
- Le ton doit etre tres formel, courtois, professionnel et soigne.
- La reponse doit ressembler a un vrai courrier serieux de suivi de dossier.
- Tu peux developper la formulation et "broder" utilement sur les formules professionnelles.
- Tu ne dois jamais inventer de faits precis non etablis.
- Tu ne dois jamais mentir ni chercher a tromper.
- Tu peux utiliser des formulations prudentes comme :
  - nous accusons reception
  - la situation est en cours d'examen
  - nous reviendrons vers vous dans les meilleurs delais
  - nous restons a disposition
- Si une reference de dossier existe dans le mail, mentionne-la.
- Si un contexte de regularisation est plausible, tu peux indiquer qu'un retour sera fait rapidement sur la suite donnee au dossier, sans promettre ce qui n'est pas etabli.
- La reponse doit etre plus detaillee qu'un simple accuse de reception.
- Termine toujours exactement par :
Samo Ferman

Email recu :
From: {email.sender}
Subject: {email.subject}
Body:
{email.body_text}

Categorie : {category}
Tags : {", ".join(tags_list) if tags_list else "Aucun"}

Resume :
{analysis.summary}

Reponse actuelle :
{analysis.suggested_reply}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    payload = json.loads(response.output_text)

    return EmailAnalysis(
        summary=analysis.summary,
        priority=analysis.priority,
        suggested_reply=ensure_email_signature(
            normalize_reply_text(payload.get("suggested_reply", analysis.suggested_reply))
        ),
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=analysis.attachment_analysis,
        detailed_summary=analysis.detailed_summary,
        category=category,
        tags=tags_list,
    )


def adapt_analysis_with_memory(
    database: Database,
    ai: AIClient,
    email: EmailMessage,
    analysis: EmailAnalysis,
    target_language: str,
) -> EmailAnalysis:
    category = getattr(analysis, "category", "Autre")
    tags = getattr(analysis, "tags", []) or []
    memories = database.list_reply_memory(category=category, tags=tags, limit=3)
    if not memories:
        return analysis

    memory_context = []
    for index, memory in enumerate(memories, start=1):
        memory_context.append(
            "\n".join(
                [
                    f"Exemple {index}",
                    f"Categorie: {memory.get('category')}",
                    f"Tags: {', '.join(memory.get('tags', [])) or 'Aucun'}",
                    f"Sujet: {memory.get('subject') or '(sans objet)'}",
                    f"Email: {memory.get('email_body') or ''}",
                    f"Reponse finale: {memory.get('final_reply') or ''}",
                ]
            )
        )

    prompt = f"""
Tu ajustes une proposition de reponse email a partir d'exemples precedemment valides par l'utilisateur.

Retourne uniquement un JSON valide avec cette structure :
{{
  "suggested_reply": "string"
}}

Regles :
- Redige en {target_language}.
- Garde le fond utile de la reponse actuelle.
- Inspire-toi du ton, du niveau de detail et du style des exemples valides ci-dessous.
- N'imite pas mecaniquement le contenu ; adapte seulement le style.
- Reste factuel, professionnel, precis et coherent avec le nouvel email.
- Termine toujours par la signature exacte : Samo Ferman

Nouvel email :
Subject: {email.subject}
Body:
{email.body_text}

Categorie: {category}
Tags: {', '.join(tags) if tags else 'Aucun'}

Reponse actuelle :
{analysis.suggested_reply}

Exemples valides :
{chr(10).join(memory_context)}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    payload = json.loads(response.output_text)

    return EmailAnalysis(
        summary=analysis.summary,
        priority=analysis.priority,
        suggested_reply=ensure_email_signature(
            normalize_reply_text(payload.get("suggested_reply", analysis.suggested_reply))
        ),
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=analysis.attachment_analysis,
        detailed_summary=analysis.detailed_summary,
        category=category,
        tags=tags,
    )


def enforce_telegram_summary_format(
    ai: AIClient,
    email: EmailMessage,
    analysis: EmailAnalysis,
    target_language: str,
) -> EmailAnalysis:
    prompt = f"""
Tu reformates un resume d'email pour qu'il soit tres utile dans une notification Telegram.

Retourne uniquement un JSON valide avec cette structure :
{{
  "summary": "string"
}}

Regles :
- Redige en {target_language}.
- Le resume doit etre plus detaille qu'un simple condensé en deux phrases.
- Il doit donner suffisamment d'elements pour comprendre rapidement le message sans ouvrir immediatement FULL ou DETAILS.
- Fais un mini briefing tres lisible.
- Utilise de preference 4 a 6 lignes courtes avec cette logique :
  Contexte : ...
  Demande : ...
  Point bloquant : ...
  Action : ...
- Si un point bloquant n'existe pas, remplace par l'information la plus importante a surveiller.
- Le resultat doit etre rapide a lire sur Telegram mais suffisamment precis pour comprendre le dossier.
- Ne fais pas un texte trop vague.

Email :
Subject: {email.subject}
Body:
{email.body_text}

Resume actuel :
{analysis.summary}

Synthese detaillee :
{getattr(analysis, "detailed_summary", analysis.summary)}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    payload = json.loads(response.output_text)
    improved_summary = (payload.get("summary") or analysis.summary).strip()

    return EmailAnalysis(
        summary=improved_summary,
        priority=analysis.priority,
        suggested_reply=analysis.suggested_reply,
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=analysis.attachment_analysis,
        detailed_summary=getattr(analysis, "detailed_summary", analysis.summary),
        category=getattr(analysis, "category", "Autre"),
        tags=getattr(analysis, "tags", []),
    )


def enforce_detailed_summary_format(
    ai: AIClient,
    email: EmailMessage,
    analysis: EmailAnalysis,
    target_language: str,
) -> EmailAnalysis:
    prompt = f"""
Tu rediges une synthese detaillee d'email pour consultation dans Telegram.

Retourne uniquement un JSON valide avec cette structure :
{{
  "detailed_summary": "string"
}}

Regles :
- Redige en {target_language}.
- La synthese detaillee doit etre nettement plus complete que le resume court.
- Elle doit permettre de comprendre le dossier sans relire le mail original.
- Sois concret, specifique et factuel.
- Reprends les demandes importantes avec de vraies precisions.
- Si le mail contient plusieurs categories de demandes, distingue-les clairement.
- Mentionne explicitement les incoherences ou les points manquants.
- N'ecris pas un simple paraphrase floue.

Structure attendue, avec de vrais contenus :
Contexte : ...
Demandes principales : ...
Precisions attendues : ...
Documents / elements mentionnes : ...
Points bloquants ou incoherences : ...
Action recommandee : ...

Email :
From: {email.sender}
Subject: {email.subject}
Body:
{email.body_text}

Pieces jointes detectees :
{", ".join(email.attachment_names) if email.attachment_names else "Aucune"}

Documents mentionnes comme fournis :
{", ".join(analysis.provided_documents) if analysis.provided_documents else "Aucun"}

Documents demandes :
{", ".join(analysis.required_documents) if analysis.required_documents else "Aucun"}

Analyse des pieces jointes :
{analysis.attachment_analysis or "Aucune analyse disponible"}

Resume court actuel :
{analysis.summary}
""".strip()

    response = ai.client.responses.create(
        model=ai.model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    payload = json.loads(response.output_text)
    improved_details = (payload.get("detailed_summary") or analysis.detailed_summary or analysis.summary).strip()

    return EmailAnalysis(
        summary=analysis.summary,
        priority=analysis.priority,
        suggested_reply=analysis.suggested_reply,
        should_reply=analysis.should_reply,
        required_documents=analysis.required_documents,
        provided_documents=analysis.provided_documents,
        attachment_analysis=analysis.attachment_analysis,
        detailed_summary=improved_details,
        category=getattr(analysis, "category", "Autre"),
        tags=getattr(analysis, "tags", []),
    )


def main() -> None:
    settings = get_settings()
    print(
        f"Surveillance Gmail active. Verification toutes les "
        f"{settings.poll_interval_seconds} secondes."
    )

    while True:
        try:
            process_once()
        except Exception as exc:
            print(f"Erreur: {exc}")

        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
