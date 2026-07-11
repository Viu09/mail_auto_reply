from __future__ import annotations

import base64
import json
from pathlib import Path

import anthropic

from app.models import EmailAnalysis, EmailMessage


CATEGORIES = [
    "Acheteur",
    "Vendeur",
    "Locataire",
    "Proprietaire",
    "Notaire",
    "Huissier",
    "Syndic",
    "Travaux",
    "Banque",
    "Administratif",
    "Commercial",
    "Support",
    "Autre",
]

TAGS = [
    "Offre", "Acquisition", "Vente", "Visite", "Financement", "Banque", "Garantie",
    "Notaire", "Compromis", "Bail", "Loyers", "Impaye", "Contentieux", "MiseEnDemeure",
    "Procedure", "Travaux", "Devis", "Planning", "Sinistre", "Assurance", "Energie",
    "Urbanisme", "Administratif", "DocumentManquant", "PieceJointeManquante", "Prioritaire",
]

# Limites prudentes pour l'envoi natif de pieces jointes a Claude.
MAX_IMAGE_BYTES = 4_500_000
MAX_PDF_BYTES = 28_000_000

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
IMAGE_SUFFIX_TO_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "target_language": {"type": "string"},
        "summary": {"type": "string"},
        "detailed_summary": {"type": "string"},
        "category": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string", "enum": TAGS}},
        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
        "should_reply": {"type": "boolean"},
        "suggested_reply": {"type": "string"},
        "required_documents": {"type": "array", "items": {"type": "string"}},
        "provided_documents": {"type": "array", "items": {"type": "string"}},
        "attachment_analysis": {"type": "string"},
    },
    "required": [
        "target_language", "summary", "detailed_summary", "category", "tags",
        "priority", "should_reply", "suggested_reply", "required_documents",
        "provided_documents", "attachment_analysis",
    ],
    "additionalProperties": False,
}


CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "category": {"type": "string"},
                },
                "required": ["id", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "category": {"type": "string"},
    },
    "required": ["summary", "category"],
    "additionalProperties": False,
}


def _system_prompt(reply_language: str, signature: str) -> str:
    return f"""
Tu es un analyste email senior tres rigoureux au service d'un professionnel de l'immobilier.
Tu analyses chaque email entrant, tu analyses aussi ses pieces jointes (images, PDF, documents) qui te sont fournies directement, puis tu proposes une reponse email directement exploitable apres validation humaine.

Tu produis uniquement un JSON valide conforme au schema impose. Tes priorites : precision factuelle, detection d'incoherences, qualite redactionnelle.

Consignes d'analyse :
- Comprends l'intention reelle de l'expediteur, pas seulement la formulation apparente.
- Distingue ce qui est demande, ce qui est affirme comme fourni, ce qui est reellement present, et ce qui manque.
- Si le mail dit que des documents sont joints mais qu'aucune piece jointe correspondante n'est presente, signale l'incoherence dans le resume et dans la reponse.
- Ne confonds pas une piece jointe manquante avec une ressource simplement disponible sur une page externe, un reseau social, un site ou un drive.

Champ target_language :
- Detecte la langue principale de l'email recu (nom en anglais : French, English, Spanish, ...). Si le mail melange plusieurs langues, prends la langue dominante.
- Par defaut, si la langue est ambigue, utilise : {reply_language}.

Champ summary (briefing court) :
- 3 a 5 lignes courtes, lisibles en un coup d'oeil, structure :
  Contexte : ...
  Demande : ...
  Point bloquant : ...
  Action : ...
- Sois CONCRET : cite les elements factuels precis (noms, montants, dates, echeances, references) plutot que des generalites.
- Suffisamment precis pour comprendre le dossier sans ouvrir le mail complet.
- Si l'email est une simple newsletter/publicite sans action, resume-le en 1 a 2 lignes claires (ne force pas la structure).

Champ detailed_summary (synthese detaillee) :
- Nettement plus complet que summary, permet de comprendre le dossier sans relire le mail.
- Presente : contexte, demandes principales, elements techniques/financiers/administratifs chiffres, documents manquants, incoherences detectees, prochaine action recommandee.
- Reprends les chiffres, dates et references exacts. Reste factuel, pas de remplissage.

Champ category : une seule categorie principale, courte (1 a 2 mots), dans la langue de l'utilisateur (francais par defaut), decrivant le TYPE d'email du point de vue de l'utilisateur qui recoit sa boite (ex : Publicite, Travail, Logement, Banque, Administratif, Reseaux sociaux, Factures, Notifications, Personnel, Voyage, Achats, Autre). Choisis une categorie generale et reutilisable, pas un intitule ultra specifique. Reutilise EXACTEMENT une categorie deja existante quand elle convient (une liste des categories deja utilisees peut t'etre fournie) pour eviter les doublons ; ne cree une nouvelle categorie que si aucune existante ne convient. Un email publicitaire/promotionnel => Publicite. Contexte immobilier professionnel (huissier, notaire, syndic, bail, procedure) => utilise une categorie metier claire (ex : Immobilier, Huissier, Notaire) si pertinent.

Champ tags : 0 a 6 tags pertinents parmi la liste imposee, cumulables. Documents annonces joints mais absents => PieceJointeManquante. Demande documentaire incomplete => DocumentManquant.

Champ priority :
- high : action rapide, engagement formel, offre, piece manquante bloquante, incoherence importante.
- medium : reponse utile attendue sans urgence immediate.
- low : informatif, promotionnel, sans action rapide.

Champ required_documents : uniquement les documents explicitement demandes a ton destinataire. Sinon liste vide.
Champ provided_documents : documents que l'expediteur affirme avoir fournis/joints. Ne compte pas ce qui est seulement accessible en externe. Sinon liste vide.
Champ attachment_analysis : compte rendu utile du contenu des pieces jointes reellement fournies (chiffres, dates, points cles). Si aucune piece jointe : "Aucune piece jointe detectee.".

Champ should_reply : false si l'email est purement automatique, publicitaire ou n'appelle pas de reponse utile (mais garde une analyse exacte).

Champ suggested_reply (reponse email professionnelle) :
- Redige entierement dans la langue detectee (target_language).
- Cordiale, precise, credible, contextuelle ; formule d'appel adaptee, paragraphes clairs, ton naturel et humain.
- Ecris comme un vrai professionnel : phrases fluides, pas de tournures robotiques ni de remplissage, pas de repetition du contenu du mail.
- Reprends les elements concrets du message (dates, references, montants) pour montrer une vraie prise en compte.
- Va droit au but tout en restant courtois ; propose une action ou une suite claire quand c'est pertinent.
- N'affirme jamais avoir recu des documents qui ne sont pas reellement presents ; si des documents annonces sont absents, signale-le poliment.
- Adapte la reponse a la combinaison categorie + tags (ex : Travaux + Devis + Planning => plus technique et operationnel ; Acheteur + Financement + Offre => oriente dossier, etapes et pieces).
- Contexte huissier / recouvrement (categorie Huissier ou tags Contentieux/MiseEnDemeure/Procedure/Impaye) : ton tres formel et soigne, courrier serieux de suivi de dossier (accuse de reception, reference du dossier si presente, indication de traitement/regularisation en cours de maniere prudente, formule de temporisation licite, disponibilite pour tout renseignement). Jamais de faits inventes, jamais de mensonge ni d'obstruction. Dans ce cas ne demande pas l'envoi de contrats/factures/justificatifs sauf si le mail le demande explicitement.
- Termine toujours EXACTEMENT par la signature :
{signature}
- N'insere pas de retours a la ligne au milieu des phrases.
""".strip()


class AIClient:
    def __init__(self, api_key: str, model: str, reply_language: str, enable_thinking: bool = False) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.reply_language = reply_language
        self.enable_thinking = enable_thinking

    # ------------------------------------------------------------------ analyse

    def analyze_email(
        self,
        email: EmailMessage,
        reply_language: str,
        signature: str,
        attachments: list[dict] | None = None,
        memory_examples: list[dict] | None = None,
        known_categories: list[str] | None = None,
    ) -> EmailAnalysis:
        content_blocks = self._build_email_content(email, memory_examples or [], known_categories or [])
        content_blocks.extend(self._build_attachment_blocks(attachments or []))

        response = self._create(
            system=_system_prompt(reply_language, signature),
            content=content_blocks,
            max_tokens=8000,
            output_schema=ANALYSIS_SCHEMA,
        )

        payload = self._extract_json(response)
        if payload is None:
            return EmailAnalysis(
                summary="Analyse indisponible (reponse du modele non exploitable).",
                detailed_summary="",
                category="Autre",
                tags=[],
                priority="medium",
                suggested_reply="",
                should_reply=False,
                required_documents=[],
                provided_documents=[],
                attachment_analysis="",
                target_language=reply_language,
            )

        return EmailAnalysis(
            summary=(payload.get("summary") or "").strip(),
            detailed_summary=(payload.get("detailed_summary") or payload.get("summary") or "").strip(),
            category=(payload.get("category") or "Autre").strip(),
            tags=[item.strip() for item in payload.get("tags", []) if isinstance(item, str) and item.strip()],
            priority=(payload.get("priority") or "medium").strip(),
            suggested_reply=(payload.get("suggested_reply") or "").strip(),
            should_reply=bool(payload.get("should_reply", True)),
            required_documents=[
                item.strip() for item in payload.get("required_documents", []) if isinstance(item, str) and item.strip()
            ],
            provided_documents=[
                item.strip() for item in payload.get("provided_documents", []) if isinstance(item, str) and item.strip()
            ],
            attachment_analysis=(payload.get("attachment_analysis") or "").strip(),
            target_language=(payload.get("target_language") or reply_language).strip(),
        )

    # ------------------------------------------------------------------ edition

    def refine_reply(
        self,
        email: EmailMessage,
        current_reply: str,
        instructions: str,
        target_language: str,
        signature: str,
        attachment_analysis: str,
    ) -> str:
        prompt = f"""
Tu retravailles une reponse email professionnelle.

Regles :
- Garde le fond utile de la reponse existante.
- Integre les consignes de l'utilisateur, meme si elles sont ecrites dans une autre langue.
- Redige l'email final uniquement dans cette langue cible : {target_language}.
- Tiens compte du message, des pieces jointes et de leur analyse.
- Si un document est annonce comme fourni mais absent, signale-le poliment.
- Ton cordial, precis, professionnel ; paragraphes courts et propres ; pas de retours a la ligne au milieu des phrases.
- Termine toujours EXACTEMENT par la signature : {signature}
- Retourne uniquement le texte final de l'email, sans commentaire.

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

        response = self._create(
            system="Tu es un assistant email professionnel. Tu renvoies uniquement le corps final de l'email.",
            content=[{"type": "text", "text": prompt}],
            max_tokens=2048,
        )
        return self._read_text_response(response)

    # ------------------------------------------------------------------ classification

    def classify_categories(
        self, items: list[dict], known_categories: list[str] | None = None
    ) -> dict[int, str]:
        """Classe un lot d'emails a partir de leurs metadonnees. Renvoie {id: categorie}."""
        if not items:
            return {}
        known = ", ".join(known_categories) if known_categories else "aucune pour l'instant"
        lines = []
        for item in items:
            snippet = (item.get("snippet") or "")[:200].replace("\n", " ")
            lines.append(
                f"- id={item['id']} | expediteur: {item.get('sender', '')} | "
                f"objet: {item.get('subject', '')} | apercu: {snippet}"
            )
        prompt = f"""
Classe chaque email dans UNE categorie courte (1 a 2 mots), du point de vue d'un utilisateur qui trie sa boite mail.
Choisis des categories generales et reutilisables (ex : Publicite, Reseaux sociaux, Banque, Factures, Travail, Logement, Administratif, Voyage, Achats, Notifications, Securite, Newsletter, Personnel).
Reutilise EXACTEMENT une categorie existante quand elle convient. Categories deja utilisees : {known}.
N'utilise "Autre" QUE si vraiment rien ne convient. Un email promotionnel/commercial => Publicite. Une alerte/notification de service (connexion, securite, maintenance) => Securite ou Notifications.

Emails a classer :
{chr(10).join(lines)}

Renvoie un JSON {{"items":[{{"id":..., "category":"..."}}, ...]}} couvrant tous les id.
""".strip()

        response = self._create(
            system="Tu es un classificateur d'emails. Tu renvoies uniquement un JSON valide conforme au schema.",
            content=[{"type": "text", "text": prompt}],
            max_tokens=4000,
            output_schema=CLASSIFY_SCHEMA,
        )
        payload = self._extract_json(response)
        if not payload:
            return {}
        result: dict[int, str] = {}
        for entry in payload.get("items", []):
            try:
                cid = int(entry.get("id"))
            except (TypeError, ValueError):
                continue
            category = (entry.get("category") or "Autre").strip() or "Autre"
            result[cid] = category
        return result

    # ------------------------------------------------------------------ documents

    def summarize_document(
        self,
        path: Path,
        mime_type: str,
        filename: str,
        known_categories: list[str] | None = None,
        context: str = "",
    ) -> dict:
        """Analyse un fichier a la demande : renvoie {summary, category}."""
        categories_hint = ""
        if known_categories:
            categories_hint = (
                "\nCategories de documents deja utilisees (reutilise-en une a l'identique si elle convient) : "
                + ", ".join(known_categories)
            )
        instructions = f"""
Analyse le fichier fourni (nom : {filename}).{categories_hint}
{f"Contexte de l'email d'origine : {context}" if context else ""}

Rends un JSON avec :
- summary : un resume clair et concret du contenu du fichier (points cles, chiffres, dates, montants, references, parties impliquees). 3 a 8 lignes. Si le fichier est illisible, explique-le.
- category : une categorie courte (1 a 2 mots) decrivant le TYPE de document (ex : Facture, Contrat, Devis, Releve, Attestation, Photo, Rapport, Administratif, Autre). Reutilise une categorie existante si elle convient.
""".strip()

        content_blocks: list[dict] = [{"type": "text", "text": instructions}]
        try:
            content_blocks.append(self._attachment_to_block(path, mime_type, filename))
        except Exception as exc:  # noqa: BLE001
            content_blocks.append({"type": "text", "text": f"Fichier illisible ({exc})."})

        response = self._create(
            system="Tu analyses des documents et renvoies uniquement un JSON valide conforme au schema.",
            content=content_blocks,
            max_tokens=2048,
            output_schema=DOCUMENT_SCHEMA,
        )
        payload = self._extract_json(response)
        if payload is None:
            return {"summary": "Analyse indisponible.", "category": "Autre"}
        return {
            "summary": (payload.get("summary") or "").strip(),
            "category": (payload.get("category") or "Autre").strip() or "Autre",
        }

    # ------------------------------------------------------------------ interne

    def _create(self, system: str, content: list[dict], max_tokens: int, output_schema: dict | None = None):
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": content}],
        }
        if not self.enable_thinking:
            kwargs["thinking"] = {"type": "disabled"}
        if output_schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}}
        return self.client.messages.create(**kwargs)

    def _build_email_content(
        self, email: EmailMessage, memory_examples: list[dict], known_categories: list[str] | None = None
    ) -> list[dict]:
        categories_block = ""
        if known_categories:
            categories_block = (
                "\n\nCategories deja utilisees (reutilise-en une a l'identique si elle convient) : "
                + ", ".join(known_categories)
            )
        memory_block = ""
        if memory_examples:
            rendered = []
            for index, memory in enumerate(memory_examples, start=1):
                rendered.append(
                    "\n".join(
                        [
                            f"Exemple {index}",
                            f"Categorie: {memory.get('category')}",
                            f"Tags: {', '.join(memory.get('tags', [])) or 'Aucun'}",
                            f"Sujet: {memory.get('subject') or '(sans objet)'}",
                            f"Reponse finale validee: {memory.get('final_reply') or ''}",
                        ]
                    )
                )
            memory_block = (
                "\n\nExemples de reponses precedemment validees par l'utilisateur "
                "(inspire-toi du ton et du niveau de detail, sans recopier le contenu) :\n"
                + "\n\n".join(rendered)
            )

        attachment_names = ", ".join(email.attachment_names) if email.attachment_names else "aucune"
        prompt = f"""
Analyse l'email suivant et ses pieces jointes fournies plus bas.

From: {email.sender}
Subject: {email.subject}
Noms des pieces jointes annoncees: {attachment_names}
Body:
{email.body_text}
{categories_block}
{memory_block}
""".strip()

        return [{"type": "text", "text": prompt}]

    def _build_attachment_blocks(self, attachments: list[dict]) -> list[dict]:
        blocks: list[dict] = []
        for attachment in attachments:
            path = Path(attachment["path"])
            mime_type = attachment.get("mime_type") or "application/octet-stream"
            filename = attachment.get("filename") or path.name
            try:
                block = self._attachment_to_block(path, mime_type, filename)
            except Exception as exc:  # noqa: BLE001
                block = {"type": "text", "text": f"Piece jointe {filename}: analyse impossible ({exc})."}
            blocks.append(block)
        return blocks

    def _attachment_to_block(self, path: Path, mime_type: str, filename: str) -> dict:
        size = path.stat().st_size
        suffix = path.suffix.lower()

        if mime_type in SUPPORTED_IMAGE_TYPES or suffix in IMAGE_SUFFIX_TO_MEDIA_TYPE:
            if size > MAX_IMAGE_BYTES:
                return {"type": "text", "text": f"Piece jointe {filename}: image trop volumineuse pour analyse directe."}
            media_type = (
                mime_type if mime_type in SUPPORTED_IMAGE_TYPES
                else IMAGE_SUFFIX_TO_MEDIA_TYPE.get(suffix, "image/jpeg")
            )
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": self._b64(path)},
            }

        if mime_type == "application/pdf" or suffix == ".pdf":
            if size > MAX_PDF_BYTES:
                return {"type": "text", "text": f"Piece jointe {filename}: PDF trop volumineux pour analyse directe."}
            return {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": self._b64(path)},
                "title": filename,
            }

        extracted = self._extract_attachment_text(path, mime_type, suffix)
        if extracted:
            return {"type": "text", "text": f"Piece jointe {filename} (contenu extrait) :\n{extracted}"}

        return {"type": "text", "text": f"Piece jointe {filename}: contenu non exploitable automatiquement."}

    @staticmethod
    def _b64(path: Path) -> str:
        return base64.standard_b64encode(path.read_bytes()).decode("utf-8")

    @staticmethod
    def _extract_attachment_text(path: Path, mime_type: str, suffix: str) -> str:
        if mime_type.startswith("text/") or suffix in {".txt", ".csv", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:20000]
        if suffix == ".docx":
            from docx import Document

            document = Document(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)[:20000]
        return ""

    @staticmethod
    def _read_text_response(response) -> str:
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
        return ""

    @staticmethod
    def _extract_json(response) -> dict | None:
        if getattr(response, "stop_reason", None) == "refusal":
            return None
        for block in response.content:
            if block.type == "text":
                try:
                    return json.loads(block.text)
                except json.JSONDecodeError:
                    return None
        return None
