"""Digest Routines : GET /api/digest, resume en lecture seule pour le hub.

Contrat : vision/docs/02-architecture.md §4 (contrat de digest v1 final) et fiche
vision/docs/contrats-digest/mail_auto_reply.md (references §x ci-dessous).

Regles tenues ici :
- lecture seule stricte : aucune ecriture, aucun appel Gmail ni Claude ;
- colonnes choisies une par une (jamais body_text, snippet, suggested_reply, token_json,
  accounts.email, reply_memory.email_body / final_reply, documents.local_path / summary) ;
- tout texte sortant est assaini (e-mail, URL, IBAN, telephone masques) puis coupe ;
- noms de personnes au format « Prenom N. », organisations en clair ;
- chaque section a sa propre session et son propre try/except : un echec est signale
  par un check section:<nom>, jamais par un message d'erreur brut.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Callable, Iterator

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import (
    Account,
    Database,
    DisabledAccount,
    Document,
    IngestState,
    ProcessedEmail,
    ReplyMemory,
    WorkerHeartbeat,
)


# ------------------------------------------------------------------ constantes

TOOL = "mail_auto_reply"
TIMEZONE = "Europe/Brussels"

SINCE_DEFAULT = timedelta(hours=24)
SINCE_MAX_AGE = timedelta(days=7)
SINCE_FUTURE_TOLERANCE = timedelta(minutes=5)

REPLY_SLA_HOURS = 48  # delai de reponse attendu (D-037 : seuils par defaut)
SLA = timedelta(hours=REPLY_SLA_HOURS)
WINDOW_ACTIONABLE = timedelta(days=14)  # W14
WINDOW_LEGAL = timedelta(days=30)  # W30
LATE_INGEST = timedelta(hours=72)  # rattrapage d'un mail ingere en retard (Nouveau(S))
LATE_NOTICE = timedelta(hours=1)  # « Releve avec N h de retard »
WORKER_SILENCE = timedelta(minutes=20)
RECONNECT_STREAK = 3

MAX_EVENTS = 20
MAX_DOCUMENT_EVENTS = 5
MAX_TODOS = 15
DOCUMENT_QUERY_LIMIT = 50
STATEMENT_TIMEOUT_MS = 5000

TITLE_MAX = 140
DETAIL_MAX = 300
CONTEXT_MAX = 200
LABEL_MAX = 80
HINT_MAX = 160
SENDER_MAX = 60
SUBJECT_MAX = 70
FILE_NAME_MAX = 60
DOCUMENT_ITEM_MAX = 60
DOCUMENT_ITEMS = 3
MAILBOX_LABEL_MAX = 60

CYCLE_SCOPE = "__cycle__"

# Vocabulaire ferme des tags (§7.5) : 26 tags de mails + 4 categories de documents.
MAIL_TAGS = (
    "Offre", "Acquisition", "Vente", "Visite", "Financement", "Banque", "Garantie",
    "Notaire", "Compromis", "Bail", "Loyers", "Impaye", "Contentieux", "MiseEnDemeure",
    "Procedure", "Travaux", "Devis", "Planning", "Sinistre", "Assurance", "Energie",
    "Urbanisme", "Administratif", "DocumentManquant", "PieceJointeManquante", "Prioritaire",
)
DOCUMENT_TAGS = ("Facture", "Contrat", "Releve", "Attestation")
TAG_VOCABULARY = frozenset(MAIL_TAGS + DOCUMENT_TAGS)
MAIL_TAG_SET = frozenset(MAIL_TAGS)

TAG_LABELS = {
    "MiseEnDemeure": "Mise en demeure",
    "Impaye": "Impayé",
    "Procedure": "Procédure",
    "Energie": "Énergie",
    "DocumentManquant": "Document manquant",
    "PieceJointeManquante": "Pièce jointe manquante",
    "Releve": "Relevé",
}

# L : juridique ou financier (§2), et ordre des libelles dans les titres (§4).
LEGAL_TAGS = ("MiseEnDemeure", "Impaye", "Contentieux", "Procedure", "Sinistre")
LEGAL_FALLBACK_LABEL = "Juridique ou financier"
LEGAL_SUBJECT = re.compile(
    r"mise en demeure|huissier|sommation|injonction|contentieux|impay|recouvrement|"
    r"dernier rappel|signification"
)
DOCUMENT_REQUEST_TAGS = frozenset({"DocumentManquant", "PieceJointeManquante"})

# E4 : pieces importantes (categories deterministes de app/services.py).
DOCUMENT_CATEGORIES = ("Contrat", "Devis", "Facture", "Attestation", "Releve")
DOCUMENT_TITLES = {
    "Contrat": "Contrat reçu",
    "Devis": "Devis reçu",
    "Facture": "Facture reçue",
    "Attestation": "Attestation reçue",
    "Releve": "Relevé reçu",
}

ANALYSIS_FAILED_PREFIX = "Analyse indisponible"

# Libelles deduits de worker_heartbeats.last_error_kind (app/worker.py:_error_kind).
ERROR_LABELS = {
    "gmail_auth": "Accès Gmail refusé : jeton expiré ou révoqué. Reconnecter la boîte.",
    "token_unreadable": "Jeton illisible : clé de chiffrement différente entre api et worker.",
    "gmail_api": "Erreur de l'API Gmail.",
    "claude_attachment": "Pièce jointe refusée par Claude (format ou contenu invalide).",
    "claude_quota": "Erreur Claude (crédit, quota ou clé).",
    "claude_unavailable": "Claude indisponible ou surchargé (erreur temporaire).",
    "claude": "Erreur Claude (voir les journaux du worker). Un mail peut bloquer la boîte.",
    "other": "Erreur inattendue (voir les journaux du worker).",
}
# Lignes ecrites avant le classement fin des erreurs Claude (last_error_kind = « claude ») :
# seul le nom de classe (last_error_class) permet alors d'affiner. Une 400 (BadRequestError)
# reste ambigue (piece jointe ou credit) et garde le libelle generique.
CLAUDE_CLASS_KINDS = {
    "AuthenticationError": "claude_quota",
    "PermissionDeniedError": "claude_quota",
    "RateLimitError": "claude_quota",
    "InternalServerError": "claude_unavailable",
    "OverloadedError": "claude_unavailable",
    "ServiceUnavailableError": "claude_unavailable",
    "APIConnectionError": "claude_unavailable",
    "APITimeoutError": "claude_unavailable",
}
RECONNECT_KINDS = frozenset({"gmail_auth", "token_unreadable"})

SECTION_LABELS = {
    "emails": "Mails",
    "replies": "Réponses",
    "documents": "Documents",
    "mailboxes": "Boîtes",
    "heartbeat": "Trace du worker",
}

SEVERITY_RANK = {"urgent": 0, "notice": 1, "info": 2}
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}
STATUS_RANK = {"ok": 0, "degraded": 1, "down": 2}


def error_label(kind: str | None, error_class: str | None = None) -> str:
    """Libelle de la derniere erreur d'une trace, jamais tire du message brut."""
    kind = kind or "other"
    if kind == "claude":
        kind = CLAUDE_CLASS_KINDS.get(error_class or "", kind)
    return ERROR_LABELS.get(kind, ERROR_LABELS["other"])


# ------------------------------------------------------------------ dates


def parse_since(raw: str | None, now: datetime) -> datetime:
    """Borne basse effective S (02 §4.1, fiche §2 et §8.4). ValueError -> 400."""
    if raw is None:
        return now - SINCE_DEFAULT
    try:
        value = datetime.fromisoformat(raw.strip())  # Python 3.11 accepte le suffixe Z
        if value.tzinfo is None:
            raise ValueError("decalage absent")  # date seule ou heure sans fuseau
        value = value.astimezone(timezone.utc).replace(microsecond=0)
    except OverflowError as exc:
        raise ValueError("since hors limites") from exc
    if value > now + SINCE_FUTURE_TOLERANCE:
        raise ValueError("since trop loin dans le futur")
    return min(max(value, now - SINCE_MAX_AGE), now)


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite renvoie des dates naives (stockees en UTC) ; Postgres des dates avec fuseau."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _days(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() // 86400))


# ------------------------------------------------------------------ assainissement (§7.4)
# Memes motifs que assainir() du hub (vision/src/lib/digest/assainir.ts, 02 §10.3), que la
# sonde de minimisation applique a la reponse reelle.

_CONTROL_SPACES = re.compile("[\t\n\v\f\r\u0085\u2028\u2029]")
_INVISIBLES = re.compile(
    "[\u0000-\u0008\u000e-\u001f\u007f-\u0084\u0086-\u009f\u00ad\u200b-\u200f"
    "\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)
_EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"]+", re.IGNORECASE)
_URL_TRAILING = re.compile(r"[.,;:!?)»\"'’]+$")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ \u00a0]?[A-Z0-9]{4}){2,7}(?:[ \u00a0]?[A-Z0-9]{1,4})?\b")
_SEP = r"[ .\-\u00a0\u202f]"


def _digit_run(low: int, high: int) -> str:
    return rf"\d(?:{_SEP}?\d){{{low - 1},{high - 1}}}"


# Telephones : prefixe international ou format belge de 9 ou 10 chiffres, jamais groupes
# par « / » ni « : » (une date « 02/11/2026 18:00 » reste intacte), jamais suivis de « € ».
_PHONE = re.compile(
    r"(?<![\w+])(?:"
    rf"(?:\+|00)32{_SEP}?(?:\(0\){_SEP}?)?{_digit_run(8, 9)}"
    rf"|(?:\+|00)[1-9]\d{{0,2}}{_SEP}?(?:\(0\){_SEP}?)?{_digit_run(7, 11)}"
    rf"|0[1-9]/{_digit_run(7, 8)}"
    rf"|0[1-9]\d/{_digit_run(6, 7)}"
    rf"|0[1-9]\d{{2}}/{_digit_run(5, 6)}"
    rf"|0[1-9](?:{_SEP}?\d){{7,8}}"
    rf")(?![\d:]|{_SEP}?(?:€|EUR\b))"
)
_SPACES = re.compile(r" {2,}")
_CUT_TRAILING = re.compile(r"[\s,;:.·—–-]+$")


def _clean_chars(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = _CONTROL_SPACES.sub(" ", value)
    value = _INVISIBLES.sub("", value)
    return _SPACES.sub(" ", value).strip()


def _mask_url(match: re.Match[str]) -> str:
    # « voir https://x.be/doc. » -> « voir [lien]. » : la ponctuation finale reste au texte.
    trailing = _URL_TRAILING.search(match.group(0))
    return "[lien]" + (trailing.group(0) if trailing else "")


def _redact(value: str | None) -> str:
    """Caviardage de tout texte sortant, avant la coupe (§7.4). E-mails avant URL, comme le hub."""
    result = _clean_chars(value or "")
    result = _EMAIL.sub("[e-mail]", result)
    result = _URL.sub(_mask_url, result)
    result = _IBAN.sub("[IBAN]", result)
    result = _PHONE.sub("[tél.]", result)
    return _SPACES.sub(" ", result).strip()


def _cut(value: str, limit: int) -> str:
    """Coupe a `limit` caracteres, « … » compris, de preference sur une fin de mot."""
    if len(value) <= limit:
        return value
    kept = value[: limit - 1]
    last_space = kept.rfind(" ")
    end = last_space if last_space >= int((limit - 1) * 0.6) else len(kept)
    return _CUT_TRAILING.sub("", kept[:end]) + "…"


def _clean(value: str | None, limit: int) -> str:
    return _cut(_redact(value), limit)


# ------------------------------------------------------------------ noms (§7.3)


def _fold(value: str) -> str:
    """Comparaison sans casse ni accents."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


_CONSUMER_DOMAINS = frozenset({
    "gmail", "googlemail", "outlook", "hotmail", "live", "msn", "yahoo", "icloud", "me",
    "skynet", "telenet", "proximus", "scarlet", "voo", "orange", "free", "laposte", "gmx",
    "proton", "protonmail",
})
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "ac", "edu"})
_ORG_MARKERS = frozenset(_fold(word) for word in (
    "étude", "cabinet", "bureau", "syndic", "agence", "immo", "immobilier", "immobilière",
    "notaires", "notariat", "avocats", "associés", "partners", "groupe", "group", "sa", "srl",
    "sprl", "scrl", "sc", "scs", "sas", "sarl", "bv", "bvba", "nv", "asbl", "vzw", "ltd",
    "gmbh", "inc", "banque", "bank", "assurance", "assurances", "insurance", "service",
    "services", "support", "info", "contact", "noreply", "team", "équipe", "administration",
    "commune", "ville", "cpas", "spf", "fod", "région", "tribunal", "justice", "ministère",
    "résidence", "copropriété", "acp", "vme", "fondation", "association", "société",
    "compagnie",
))
_CIVILITIES = frozenset({"m", "mr", "mme", "mlle", "monsieur", "madame", "me", "maitre", "dr"})
_CIVILITY_PATTERN = r"(?:(?:m|mr|mme|mlle|monsieur|madame|me|maitre|dr)\.?\s+)?"
_NAME_WORD = re.compile(r"^[^\W\d_]+(?:['’-][^\W\d_]+)*$")
NO_NAME = "Expéditeur sans nom"


@dataclass(frozen=True)
class SenderName:
    display: str
    # Formes du nom complet a remplacer dans les textes libres (personnes seulement).
    patterns: tuple[str, ...] = ()


def _title_case(word: str) -> str:
    if word.islower() or word.isupper():
        return re.sub(r"(^|[-'’])(\w)", lambda m: m.group(1) + m.group(2).upper(), word.lower())
    return word


def _initial(word: str) -> str:
    # Particule comprise : « Van der Berg » -> « V. », « d'Ormesson » -> « D. ».
    letters = [ch for ch in word if ch.isalpha()]
    return letters[0].upper() if letters else ""


def _domain_name(address: str) -> str:
    if "@" not in address:
        return NO_NAME
    domain = address.rsplit("@", 1)[1].strip().strip("<>").lower().rstrip(".")
    labels = [label for label in domain.split(".") if label]
    if len(labels) < 2:
        return NO_NAME
    core = labels[-2]
    if core in _SECOND_LEVEL and len(labels) >= 3:
        core = labels[-3]
    if core in _CONSUMER_DOMAINS or not re.fullmatch(r"[a-z0-9-]{1,60}", core):
        return NO_NAME
    return core


def sender_name(sender: str | None) -> SenderName:
    """Regle « Prenom N. » (§7.3) : personne reduite, organisation en clair."""
    result = _sender_name(sender)
    return SenderName(_cut(_redact(result.display), SENDER_MAX) or NO_NAME, result.patterns)


def _sender_name(sender: str | None) -> SenderName:
    raw_name, address = parseaddr(sender or "")
    name = re.sub(r"\([^)]*\)", " ", raw_name)
    name = re.sub(r"[\"“”«»]", " ", name)
    name = _clean_chars(name)
    if not name or "@" in name:
        return SenderName(_domain_name(address or raw_name))

    folded_tokens = re.findall(r"[a-z0-9]+", _fold(name).replace(".", ""))
    if any(ch.isdigit() for ch in name) or "&" in name or any(t in _ORG_MARKERS for t in folded_tokens):
        return SenderName(name)

    # Forme « Nom, Prenom » (carnets d'adresses Outlook) : remise dans l'ordre.
    if name.count(",") == 1:
        last_part, first_part = (part.strip() for part in name.split(","))
        name = f"{first_part} {last_part}".strip()
    elif "," in name:
        name = " ".join(name.replace(",", " ").split())  # en cas de doute, la regle reduit

    words = name.split()
    civility = None
    while words and _fold(words[0]).rstrip(".") in _CIVILITIES:
        civility = civility or words[0]
        words = words[1:]

    if not words or not all(_NAME_WORD.match(word) for word in words):
        return SenderName(name)

    if len(words) == 1:
        if civility is None:
            return SenderName(name)  # prenom seul ou organisation
        display = f"{_title_case(civility)} {_initial(words[0])}."
        return SenderName(display, _name_patterns([words[0]], words[0], words[0]))

    if len(words) > 4:
        return SenderName(name)

    if all(word.isupper() for word in words):
        display = " ".join(f"{_initial(word)}." for word in words)  # par prudence
        first, last = words[0], words[1:]
    elif words[0].isupper() and not words[-1].isupper():
        first, last = words[-1], words[:-1]  # ordre « NOM Prenom »
        display = f"{_title_case(first)} {_initial(last[0])}."
    else:
        first, last = words[0], words[1:]
        display = f"{_title_case(first)} {_initial(last[0])}."
    return SenderName(display, _name_patterns(words, first, " ".join(last)))


def _name_patterns(words: list[str], first: str, last: str) -> tuple[str, ...]:
    forms = {_fold(" ".join(words))}
    if first != last:
        forms.add(_fold(f"{first} {last}"))
        forms.add(_fold(f"{last} {first}"))
    if sum(ch.isalpha() for ch in last) >= 3:
        forms.add(_fold(last))
    return tuple(sorted(forms, key=len, reverse=True))


def _form_pattern(form: str) -> str:
    pieces = []
    for ch in form:
        if ch.isspace():
            pieces.append(r"\s+")
        elif ch in "'’":
            pieces.append("['’]")
        else:
            pieces.append(re.escape(ch))
    return "".join(pieces)


def _replace_sender(value: str, sender: SenderName) -> str:
    """Remplace le nom complet de l'expediteur par sa forme reduite (mot entier, sans casse
    ni accents). Les noms de tiers ne sont pas detectables : risque residuel (§11)."""
    if not sender.patterns or not value:
        return value
    folded_chars: list[str] = []
    origin: list[int] = []
    for index, ch in enumerate(value):
        piece = _fold(ch)
        folded_chars.append(piece)
        origin.extend([index] * len(piece))
    folded = "".join(folded_chars)
    alternatives = "|".join(_form_pattern(form) for form in sender.patterns)
    pattern = re.compile(rf"(?<!\w){_CIVILITY_PATTERN}(?:{alternatives})(?!\w)")
    spans = [(origin[m.start()], origin[m.end() - 1] + 1) for m in pattern.finditer(folded) if m.end() > m.start()]
    for start, end in reversed(spans):
        if sender.display.endswith(".") and value[end:end + 1] == ".":
            end += 1  # « … Dumont. » -> « … Maitre D. » et non « D.. »
        value = value[:start] + sender.display + value[end:]
    return value


def _free_text(value: str | None, sender: SenderName, limit: int) -> str:
    """Texte libre d'un mail : caviardage, nom de l'expediteur reduit, puis coupe."""
    return _cut(_replace_sender(_redact(value), sender), limit)


# ------------------------------------------------------------------ resume IA


_SUMMARY_PREFIX = re.compile(r"^[\s\-*•·>#]+")
_SUMMARY_LABEL = re.compile(r"^(demandes?|actions?)\b[^:]{0,30}:")


def _summary_lines(summary: str | None) -> str:
    """Lignes « Demande » et « Action » du resume IA, jointes par « · » (a defaut, la 1re)."""
    lines = []
    for line in (summary or "").splitlines():
        bare = _SUMMARY_PREFIX.sub("", line).replace("**", "").replace("__", "").strip()
        if bare:
            lines.append(bare)
    kept = []
    for line in lines:
        match = _SUMMARY_LABEL.match(_fold(line))
        if match is None:
            continue
        content = line.split(":", 1)[1].strip() if ":" in line else ""
        if content:
            label = "Demande" if match.group(1).startswith("demande") else "Action"
            kept.append(f"{label} : {content}")
    if not kept and lines:
        kept = [lines[0]]
    return " · ".join(kept)


# ------------------------------------------------------------------ mails


@dataclass
class _Mail:
    id: int
    thread: str
    todo_id: str
    account_id: str
    sender: SenderName
    subject: str
    summary: str
    tags: list[str]
    priority: str
    should_reply: bool
    status: str
    required_documents: list[str]
    received_at: datetime
    created_at: datetime
    legal: bool = False
    analysis_failed: bool = False

    @property
    def recorded_at(self) -> datetime:
        return max(self.received_at, self.created_at)


_THREAD_ID = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _tag_list(raw: Any) -> list[str]:
    """Tags d'un mail : intersection avec le vocabulaire ferme (les categories de documents
    ne sont emises que sur document.received)."""
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for tag in raw:
        if isinstance(tag, str) and tag in MAIL_TAG_SET and tag not in tags:
            tags.append(tag)
    return tags


def _str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _is_legal(tags: list[str], subject: str) -> bool:
    if any(tag in LEGAL_TAGS for tag in tags):
        return True
    return LEGAL_SUBJECT.search(" ".join(_fold(subject).split())) is not None


def _legal_label(tags: list[str]) -> str:
    for tag in LEGAL_TAGS:
        if tag in tags:
            return TAG_LABELS.get(tag, tag)
    return LEGAL_FALLBACK_LABEL


def _is_new(received_at: datetime, created_at: datetime, since: datetime) -> bool:
    """Nouveau(S) (§2) : recu apres S, ou ingere apres S et recu moins de 72 h avant S."""
    return received_at > since or (created_at > since and received_at > since - LATE_INGEST)


def _late_prefix(received_at: datetime, created_at: datetime) -> str | None:
    delay = created_at - received_at
    if delay >= LATE_NOTICE:
        return f"Relevé avec {int(delay.total_seconds() // 3600)} h de retard"
    return None


def _subject(mail: _Mail) -> str:
    subject = mail.subject.strip()
    if not subject:
        return "(sans objet)"
    return _free_text(subject, mail.sender, SUBJECT_MAX)


def _who(mail: _Mail) -> str:
    return f"{_cut(mail.sender.display, SENDER_MAX)} — {_subject(mail)}"


def _requested_documents(mail: _Mail) -> str:
    items = [_free_text(item, mail.sender, DOCUMENT_ITEM_MAX) for item in mail.required_documents[:DOCUMENT_ITEMS]]
    return ", ".join(item for item in items if item)


@dataclass
class _Mailbox:
    account_id: str
    alias: str
    display: str  # « Boite principale », « Boite n°k » ou « Boite « Agence » »
    title_name: str  # pour « Reconnecter la boite Gmail … »
    source: str  # env | oauth


def mailbox_alias(account_id: str) -> str:
    """Alias stable d'une boite : l'id d'un compte OAuth derive de son adresse e-mail (§1)."""
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ sections


@contextmanager
def _read_session(database: Database) -> Iterator[Session]:
    with database.session() as session:
        if database.engine.dialect.name == "postgresql":
            # Garde-fou (§8.5) : ce n'est pas une ecriture, la transaction reste en lecture.
            session.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        yield session


def _check_database(database: Database) -> bool:
    try:
        with _read_session(database) as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001  (classe seulement, jamais le message)
        print(f"[digest] base injoignable : {type(exc).__name__}")
        return False


def _load_mails(database: Database, owner: str, now: datetime) -> list[_Mail]:
    """Q1 : une seule requete pour indicateurs, evenements E1-E3 et a-faire T1-T4, T6."""
    columns = (
        ProcessedEmail.id, ProcessedEmail.thread_id, ProcessedEmail.account_id,
        ProcessedEmail.sender, ProcessedEmail.subject, ProcessedEmail.summary,
        ProcessedEmail.tags, ProcessedEmail.priority, ProcessedEmail.should_reply,
        ProcessedEmail.approval_status, ProcessedEmail.required_documents,
        ProcessedEmail.received_at, ProcessedEmail.created_at,
    )
    with _read_session(database) as session:
        rows = session.execute(
            select(*columns).where(
                ProcessedEmail.owner == owner,
                ProcessedEmail.received_at >= now - WINDOW_LEGAL,
            )
        ).all()
    mails = []
    for row in rows:
        received_at = _as_utc(row.received_at)
        if received_at is None:
            continue
        thread_id = (row.thread_id or "").strip()
        tags = _tag_list(row.tags)
        subject = row.subject or ""
        summary = row.summary or ""
        mails.append(_Mail(
            id=int(row.id),
            thread=thread_id or f"email:{row.id}",
            todo_id=f"thread:{thread_id}" if _THREAD_ID.match(thread_id) else f"email:{row.id}",
            account_id=row.account_id or "",
            sender=sender_name(row.sender),
            subject=subject,
            summary=summary,
            tags=tags,
            priority=(row.priority or "medium"),
            should_reply=bool(row.should_reply),
            status=(row.approval_status or "pending"),
            required_documents=_str_list(row.required_documents),
            received_at=received_at,
            created_at=_as_utc(row.created_at) or received_at,
            legal=_is_legal(tags, subject),
            analysis_failed=summary.startswith(ANALYSIS_FAILED_PREFIX),
        ))
    return mails


def _count_replies(database: Database, owner: str, since: datetime) -> int:
    """Q2 : seulement owner et created_at de reply_memory, jamais les textes."""
    with _read_session(database) as session:
        return int(session.execute(
            select(func.count(ReplyMemory.id)).where(
                ReplyMemory.owner == owner,
                ReplyMemory.created_at > since,
            )
        ).scalar() or 0)


def _load_documents(database: Database, owner: str, since: datetime) -> list[Any]:
    """Q3 : pieces importantes recentes, sans local_path ni summary."""
    columns = (
        Document.id, Document.email_id, Document.account_id, Document.file_name,
        Document.category, Document.sender, Document.received_at, Document.created_at,
    )
    with _read_session(database) as session:
        return session.execute(
            select(*columns)
            .where(
                Document.owner == owner,
                Document.received_at > since - LATE_INGEST,
                Document.category.in_(DOCUMENT_CATEGORIES),
            )
            .order_by(Document.received_at.desc(), Document.id.desc())
            .limit(DOCUMENT_QUERY_LIMIT)
        ).all()


def _load_mailboxes(database: Database, settings: Settings, owner: str) -> list[_Mailbox]:
    """Q5 : boites du proprietaire principal, sans jamais dechiffrer de jeton (§6)."""
    with _read_session(database) as session:
        disabled = {row[0] for row in session.execute(select(DisabledAccount.id)).all()}
        oauth_rows = session.execute(
            select(Account.id, Account.label).where(Account.owner == owner).order_by(Account.created_at.asc())
        ).all()
    # Les comptes definis par variables d'environnement appartiennent au proprietaire principal.
    entries = [(a.id, a.label or "", "env") for a in settings.accounts if a.id not in disabled]
    entries += [(row[0], row[1] or "", "oauth") for row in oauth_rows]

    mailboxes = []
    for position, (account_id, label, source) in enumerate(entries, start=1):
        label = label.strip()
        if not label or label == account_id:
            display, title_name = "Boîte principale", "principale"
        elif "@" in label:
            display, title_name = f"Boîte n°{position}", f"n°{position}"
        else:
            cleaned = _clean(label, MAILBOX_LABEL_MAX)
            display, title_name = f"Boîte « {cleaned} »", f"« {cleaned} »"
        mailboxes.append(_Mailbox(account_id, mailbox_alias(account_id), display, title_name, source))
    return mailboxes


def _load_heartbeats(database: Database) -> tuple[dict[str, Any], dict[str, bool]]:
    """Q4 et Q6 : trace du worker et etat du rattrapage d'historique (lecture seule)."""
    with _read_session(database) as session:
        beats = {
            row.scope: row
            for row in session.execute(
                select(
                    WorkerHeartbeat.scope, WorkerHeartbeat.last_seen_at, WorkerHeartbeat.last_success_at,
                    WorkerHeartbeat.last_error_at, WorkerHeartbeat.last_error_kind,
                    WorkerHeartbeat.last_error_class, WorkerHeartbeat.fail_streak,
                )
            ).all()
        }
        backfill = {
            row[0]: bool(row[1])
            for row in session.execute(select(IngestState.account_id, IngestState.backfill_done)).all()
        }
    return beats, backfill


# ------------------------------------------------------------------ construction


@dataclass
class _Parts:
    checks: list[dict] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    events: list[tuple[tuple, dict]] = field(default_factory=list)
    document_events: list[tuple[tuple, dict]] = field(default_factory=list)
    todos: list[tuple[tuple, dict]] = field(default_factory=list)
    failed_sections: list[str] = field(default_factory=list)

    def merge(self, other: _Parts) -> None:
        self.checks += other.checks
        self.metrics += other.metrics
        self.events += other.events
        self.document_events += other.document_events
        self.todos += other.todos


_FAILED = object()


def _section(name: str, parts: _Parts, compute: Callable[[_Parts], Any]) -> Any:
    """Execute une section dans son propre try/except. Ses elements ne sont ajoutes au
    digest que si elle aboutit : une section en echec n'emet rien de partiel (§8.7)."""
    local = _Parts()
    try:
        result = compute(local)
    except Exception as exc:  # noqa: BLE001  (classe seulement, jamais le message)
        print(f"[digest] section {name} : {type(exc).__name__}")
        parts.failed_sections.append(name)
        return _FAILED
    parts.merge(local)
    return result


def _metric(key: str, label: str, value: int, unit: str, *, window: str | None = None, hint: str | None = None) -> dict:
    metric: dict[str, Any] = {"key": key, "label": _cut(label, LABEL_MAX), "value": value, "unit": unit}
    if window:
        metric["window"] = window
    if hint:
        metric["hint"] = _cut(hint, HINT_MAX)
    return metric


def _event(event_id: str, kind: str, at: datetime, title: str, detail: str, severity: str, url: str, tags: list[str]) -> tuple[tuple, dict]:
    event: dict[str, Any] = {"id": event_id, "type": kind, "at": _iso(at), "title": _clean(title, TITLE_MAX)}
    detail = _clean(detail, DETAIL_MAX)
    if detail:
        event["detail"] = detail
    event["severity"] = severity
    event["url"] = url
    if tags:
        event["tags"] = tags
    return (SEVERITY_RANK[severity], -at.timestamp(), event_id), event


def _todo(
    todo_id: str,
    kind: str,
    title: str,
    priority: str,
    *,
    due: datetime | None = None,
    now: datetime | None = None,
    url: str | None = None,
    context: str = "",
    tags: list[str] | None = None,
) -> tuple[tuple, dict]:
    todo: dict[str, Any] = {"id": todo_id, "type": kind, "title": _clean(title, TITLE_MAX)}
    overdue = None
    if due is not None:
        todo["dueAt"] = _iso(due)
        if now is not None and now >= due:
            overdue = _days(now - due)
            todo["overdueDays"] = overdue
    todo["priority"] = priority
    if url:
        todo["url"] = url
    context = _clean(context, CONTEXT_MAX)
    if context:
        todo["context"] = context
    if tags:
        todo["tags"] = tags
    sort_key = (
        PRIORITY_RANK[priority],
        0 if overdue is not None else 1,
        -(overdue or 0),
        0 if due is not None else 1,
        due.timestamp() if due is not None else 0.0,
        todo_id,
    )
    return sort_key, todo


def _mail_context(mail: _Mail, mailbox_names: dict[str, str]) -> str:
    """« Priorite haute · Tags : … · Documents demandes : … · Boite « … » » (sans date, §5)."""
    parts = []
    if mail.priority == "high":
        parts.append("Priorité haute")
    mail_tags = [tag for tag in mail.tags if tag in MAIL_TAGS]
    if mail_tags:
        parts.append("Tags : " + ", ".join(TAG_LABELS.get(tag, tag) for tag in mail_tags))
    documents = _requested_documents(mail)
    if documents:
        parts.append(f"Documents demandés : {documents}")
    mailbox = mailbox_names.get(mail.account_id)
    if mailbox:
        parts.append(mailbox)
    return " · ".join(parts)


def _mail_detail(mail: _Mail, prefixes: list[str]) -> str:
    parts = [p for p in prefixes if p]
    lines = _summary_lines(mail.summary)
    if lines:
        parts.append(_replace_sender(_redact(lines), mail.sender))
    return " · ".join(parts)


def _emails_section(parts: _Parts, mails: list[_Mail], mailbox_names: dict[str, str], since: datetime, now: datetime) -> set[int]:
    """Indicateurs « en attente » et received_since, evenements E1-E3, a-faire T1-T4 et T6."""
    w14 = now - WINDOW_ACTIONABLE
    overdue_limit = now - SLA

    # Un seul mail en attente par fil, le plus recent (§2, « Fil »).
    latest: dict[str, _Mail] = {}
    for mail in mails:
        if mail.status != "pending":
            continue
        current = latest.get(mail.thread)
        if current is None or (mail.received_at, mail.id) > (current.received_at, current.id):
            latest[mail.thread] = mail
    pending = list(latest.values())

    urgent = [m for m in pending if m.legal]
    actionable = [m for m in pending if m.should_reply and m.received_at >= w14]
    overdue = [m for m in actionable if m.received_at <= overdue_limit]
    high = [m for m in actionable if m.priority == "high"]
    oldest = _days(now - min(m.received_at for m in overdue)) if overdue else 0
    received_since = sum(1 for m in mails if m.should_reply and _is_new(m.received_at, m.created_at, since))

    parts.metrics += [
        _metric("urgent_pending", "Mails juridiques ou financiers en attente", len(urgent), "count",
                hint="Reçus ces 30 derniers jours, comptés par fil"),
        _metric("overdue_replies", "Réponses en retard (plus de 48 h)", len(overdue), "count",
                hint="Mails reçus ces 14 derniers jours"),
        _metric("oldest_overdue_days", "Plus ancienne réponse en attente (jours depuis réception)", oldest, "days"),
        _metric("high_priority_pending", "Mails prioritaires en attente", len(high), "count"),
        _metric("actionable_pending", "Mails à traiter", len(actionable), "count",
                hint="Hors publicité et mails filtrés, reçus ces 14 derniers jours"),
        _metric("received_since", "Mails utiles reçus depuis le dernier point", received_since, "count",
                window="since"),
    ]

    # Evenements : un au plus par mail (E1 > E2 > E3), puis un seul par fil.
    by_thread: dict[str, tuple[tuple, dict, int]] = {}
    for mail in mails:
        if not _is_new(mail.received_at, mail.created_at, since):
            continue
        late = _late_prefix(mail.received_at, mail.created_at)
        is_pending_useful = mail.status == "pending" and mail.should_reply
        if mail.legal:
            status_prefix = {"sent": "Déjà répondu", "rejected": "Refusé"}.get(mail.status)
            item = _event(f"email:{mail.id}", "mail.legal_alert", mail.recorded_at,
                          f"{_legal_label(mail.tags)} : {_who(mail)}",
                          _mail_detail(mail, [status_prefix, late]), "urgent", "/inbox", mail.tags)
        elif is_pending_useful and mail.priority == "high":
            item = _event(f"email:{mail.id}", "mail.priority", mail.recorded_at,
                          f"Mail prioritaire : {_who(mail)}",
                          _mail_detail(mail, [late]), "notice", "/inbox", mail.tags)
        elif is_pending_useful and (mail.required_documents or DOCUMENT_REQUEST_TAGS.intersection(mail.tags)):
            documents = _requested_documents(mail)
            item = _event(f"email:{mail.id}", "mail.documents_requested", mail.recorded_at,
                          f"Documents demandés : {_who(mail)}",
                          _mail_detail(mail, [late, f"Documents demandés : {documents}" if documents else None]),
                          "notice", "/inbox", mail.tags)
        else:
            continue
        current = by_thread.get(mail.thread)
        if current is None or item[0] < current[0]:
            by_thread[mail.thread] = (item[0], item[1], mail.id)
    parts.events += [(key, event) for key, event, _ in by_thread.values()]
    emitted_mail_ids = {mail_id for _, _, mail_id in by_thread.values()}

    # A-faire : un au plus par fil, sur le mail en attente le plus recent (T1 > T2 > T3 > T4).
    for mail in pending:
        due = mail.received_at + SLA
        recent = mail.received_at > overdue_limit
        if mail.legal:
            parts.todos.append(_todo(
                mail.todo_id, "mail.legal_pending",
                f"Traiter : {_legal_label(mail.tags)} · {_who(mail)}", "high",
                due=due, now=now, url="/inbox",
                context=_mail_context(mail, mailbox_names), tags=mail.tags))
        elif mail.should_reply and mail.received_at >= w14 and not recent:
            priority = {"high": "high", "low": "low"}.get(mail.priority, "normal")
            parts.todos.append(_todo(
                mail.todo_id, "mail.reply_overdue", f"Répondre à {_who(mail)}", priority,
                due=due, now=now, url="/inbox",
                context=_mail_context(mail, mailbox_names), tags=mail.tags))
        elif mail.should_reply and recent and mail.priority == "high":
            parts.todos.append(_todo(
                mail.todo_id, "mail.reply_priority", f"Répondre à {_who(mail)}", "normal",
                due=due, now=now, url="/inbox",
                context=_mail_context(mail, mailbox_names), tags=mail.tags))
        elif mail.should_reply and recent and mail.required_documents:
            parts.todos.append(_todo(
                mail.todo_id, "mail.documents_to_send",
                f"Envoyer les documents demandés à {_who(mail)}", "normal",
                due=due, now=now, url="/inbox",
                context=_mail_context(mail, mailbox_names), tags=mail.tags))

    # T6 : agrege, mails en attente sans resume IA.
    failed = sum(1 for m in mails if m.status == "pending" and m.received_at >= w14 and m.analysis_failed)
    if failed:
        title = f"{failed} mail à lire sans résumé IA" if failed == 1 else f"{failed} mails à lire sans résumé IA"
        parts.todos.append(_todo(
            "inbox:analysis_failed", "mail.analysis_failed", title, "low", url="/inbox",
            context="L'analyse automatique a échoué : ouvrir et lire à la main"))
    return emitted_mail_ids


def _documents_section(parts: _Parts, rows: list[Any], excluded_mail_ids: set[int], since: datetime) -> None:
    for row in rows:
        received_at = _as_utc(row.received_at)
        if received_at is None:
            continue
        created_at = _as_utc(row.created_at) or received_at
        if not _is_new(received_at, created_at, since):
            continue
        if row.email_id is not None and int(row.email_id) in excluded_mail_ids:
            continue
        sender = sender_name(row.sender)
        file_name = _free_text(row.file_name or "fichier", sender, FILE_NAME_MAX)
        category = row.category
        late = _late_prefix(received_at, created_at)
        detail = " · ".join(p for p in (late, f"Pièce classée « {category} » dans les documents") if p)
        parts.document_events.append(_event(
            f"document:{row.id}", "document.received", max(received_at, created_at),
            f"{DOCUMENT_TITLES.get(category, category)} : {_cut(sender.display, SENDER_MAX)} — {file_name}",
            detail, "info", "/documents", [category] if category in TAG_VOCABULARY else []))


def _worker_check(beats: dict[str, Any], now: datetime) -> dict:
    check: dict[str, Any] = {"key": "worker", "label": "Analyse des mails (worker)"}
    cycle = beats.get(CYCLE_SCOPE)
    if cycle is None:
        check.update(status="degraded", detail="Aucun signal du worker (pas encore redéployé ?)")
        return check
    last_seen = _as_utc(cycle.last_seen_at)
    last_success = _as_utc(cycle.last_success_at)
    last_error = _as_utc(cycle.last_error_at)
    failed = last_error is not None and (last_success is None or last_error > last_success)
    if last_seen is None or now - last_seen > WORKER_SILENCE:
        check.update(status="degraded", detail="Worker silencieux depuis plus de 20 min")
    elif failed:
        label = error_label(cycle.last_error_kind, cycle.last_error_class)
        check.update(status="degraded", detail=f"Dernier cycle en erreur : {label}")
    else:
        check["status"] = "ok"
    if last_success is not None:
        check["lastSuccessAt"] = _iso(last_success)
    return check


def _heartbeat_section(
    parts: _Parts,
    beats: dict[str, Any],
    backfill: dict[str, bool],
    mailboxes: list[_Mailbox] | None,
    now: datetime,
) -> None:
    """Checks worker et mailbox:*, a-faire T5 (trace worker_heartbeats, D-036)."""
    parts.checks.append(_worker_check(beats, now))
    for mailbox in mailboxes or []:
        check: dict[str, Any] = {"key": f"mailbox:{mailbox.alias}", "label": _cut(mailbox.display, LABEL_MAX)}
        beat = beats.get(mailbox.account_id)
        details = []
        if beat is None:
            status = "degraded"
            details.append("Aucune relève enregistrée pour cette boîte")
        elif int(beat.fail_streak or 0) >= 1:
            status = "degraded"
            details.append(error_label(beat.last_error_kind, beat.last_error_class))
        else:
            status = "ok"
        if backfill.get(mailbox.account_id) is False:
            details.append("Rattrapage de l'historique en cours")
        check["status"] = status
        if details:
            check["detail"] = _cut(" · ".join(details), DETAIL_MAX)
        last_success = _as_utc(beat.last_success_at) if beat is not None else None
        if last_success is not None:
            check["lastSuccessAt"] = _iso(last_success)
        parts.checks.append(check)

        # T5 : boite a reconnecter.
        if beat is not None and beat.last_error_kind in RECONNECT_KINDS and int(beat.fail_streak or 0) >= RECONNECT_STREAK:
            if mailbox.source == "oauth":
                reason = "Jeton expiré ou révoqué" if beat.last_error_kind == "gmail_auth" else "Jeton illisible"
                context, url = f"{reason} : la relève de cette boîte est arrêtée", "/settings"
            else:
                context, url = "Action développeur : régénérer le jeton (variable Railway)", None
            parts.todos.append(_todo(
                f"mailbox:{mailbox.alias}:reconnect", "mailbox.reconnect",
                f"Reconnecter la boîte Gmail {mailbox.title_name}", "high", url=url, context=context))


def _base(now: datetime, since: datetime) -> dict:
    return {"version": 1, "tool": TOOL, "generatedAt": _iso(now), "since": _iso(since), "timezone": TIMEZONE}


def build_digest(database: Database, settings: Settings, since: datetime, now: datetime) -> tuple[int, dict]:
    """Construit le digest. Renvoie (200, DigestV1) ou (503, DigestV1 minimal) si la base est injoignable."""
    body = _base(now, since)
    if not _check_database(database):
        body["health"] = {
            "status": "down",
            "checks": [{"key": "database", "label": "Base de données", "status": "down",
                        "detail": "Base de données injoignable"}],
        }
        body.update(metrics=[], events=[], todos=[])
        return 503, body

    owner = settings.primary_owner
    parts = _Parts()
    parts.checks.append({"key": "database", "label": "Base de données", "status": "ok"})

    loaded = _section("mailboxes", parts, lambda _: _load_mailboxes(database, settings, owner))
    mailboxes: list[_Mailbox] | None = None if loaded is _FAILED else loaded
    mailbox_names = {m.account_id: m.display for m in mailboxes or []}

    emitted = _section("emails", parts, lambda local: _emails_section(
        local, _load_mails(database, owner, now), mailbox_names, since, now))
    emitted_mail_ids: set[int] = set() if emitted is _FAILED else emitted

    _section("replies", parts, lambda local: local.metrics.append(_metric(
        "replies_sent_since", "Réponses envoyées depuis le dernier point",
        _count_replies(database, owner, since), "count",
        window="since", hint="Envois depuis l'outil, manuels et automatiques")))

    _section("documents", parts, lambda local: _documents_section(
        local, _load_documents(database, owner, since), emitted_mail_ids, since))

    # Sans liste des boites (section mailboxes en echec), ni mailbox:* ni T5 (§6).
    _section("heartbeat", parts, lambda local: _heartbeat_section(
        local, *_load_heartbeats(database), mailboxes, now))

    for name in dict.fromkeys(parts.failed_sections):
        parts.checks.append({
            "key": f"section:{name}",
            "label": _cut(f"Section « {SECTION_LABELS.get(name, name)} » indisponible", LABEL_MAX),
            "status": "degraded",
            "detail": "Lecture impossible",
        })

    # Plafonds et ordre (02 §4.3, fiche §8.6) ; truncated compte exactement les omissions.
    documents_sorted = sorted(parts.document_events, key=lambda item: item[0])
    omitted_events = max(0, len(documents_sorted) - MAX_DOCUMENT_EVENTS)
    events = sorted(parts.events + documents_sorted[:MAX_DOCUMENT_EVENTS], key=lambda item: item[0])
    omitted_events += max(0, len(events) - MAX_EVENTS)
    todos = sorted(parts.todos, key=lambda item: item[0])
    omitted_todos = max(0, len(todos) - MAX_TODOS)

    worst = max((STATUS_RANK[c["status"]] for c in parts.checks), default=0)
    # Une reponse 200 ne porte que ok ou degraded (02 §4.4) : down est reserve au 503.
    body["health"] = {"status": "degraded" if worst >= 1 else "ok", "checks": parts.checks}
    body["metrics"] = parts.metrics
    body["events"] = [event for _, event in events[:MAX_EVENTS]]
    body["todos"] = [todo for _, todo in todos[:MAX_TODOS]]
    truncated = {}
    if omitted_events:
        truncated["events"] = omitted_events
    if omitted_todos:
        truncated["todos"] = omitted_todos
    if truncated:
        body["truncated"] = truncated
    return 200, body
