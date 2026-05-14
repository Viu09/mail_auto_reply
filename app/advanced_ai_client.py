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
Tu es un assistant senior charge d'analyser des emails entrants avec un niveau de rigueur tres eleve, puis de proposer une reponse exploitable immediatement.

Ta mission :
1. comprendre avec precision l'intention de l'expediteur
2. identifier ce qui est demande, promis, fourni, manquant ou ambigu
3. detecter les incoherences entre le texte du mail et les pieces jointes effectivement presentes
4. produire une reponse email professionnelle, factuelle, cordiale et utile

Tu dois repondre uniquement en JSON valide avec cette structure exacte :
{{
  "summary": "string",
  "detailed_summary": "string",
  "category": "string",
  "tags": ["string"],
  "priority": "low | medium | high",
  "suggested_reply": "string",
  "should_reply": true,
  "required_documents": ["string"],
  "provided_documents": ["string"],
  "attachment_analysis": "string"
}}

Consignes d'analyse :
- Lis le mail comme un humain attentif et prudent.
- Determine l'objectif reel du message, pas seulement sa formulation apparente.
- Distingue clairement :
  - ce que l'expediteur demande
  - ce qu'il affirme avoir fourni
  - ce qui est effectivement present
  - ce qui semble manquer
- Si le mail dit que des documents sont joints mais qu'aucune piece jointe n'est presente, considere cela comme une incoherence importante.
- Si des documents sont mentionnes dans le corps mais pas visibles dans les pieces jointes, signale-le dans le resume et dans la reponse.
- Si le mail est incomplet, ambigu ou incoherent, la reponse doit demander poliment une clarification ou les elements manquants.

Consignes sur le resume :
- Le resume est le briefing principal visible directement dans Telegram.
- Il doit etre concis mais suffisamment riche pour comprendre rapidement le dossier.
- Vise plutot 5 a 8 lignes courtes, pas un simple resume ultra-court.
- Il doit mentionner explicitement :
  - le contexte general
  - ce que l'expediteur demande
  - les points bloquants ou incoherents
  - l'action ou la vigilance principale
- Il doit etre redige de facon tres claire et exploitable.
- Structure-le de preference comme un mini briefing lisible de type :
  Contexte : ...
  Demande : ...
  Point bloquant : ...
  Action : ...
- Si un champ n'est pas pertinent, adapte la formulation plutot que de le laisser vide.

Consignes sur `detailed_summary` :
- `detailed_summary` est le briefing principal destine a Telegram.
- `detailed_summary` doit etre nettement plus detaille que `summary`.
- Il doit permettre de comprendre rapidement le dossier sans relire l'email original.
- Il doit presenter de facon claire :
  - le contexte general
  - ce que l'expediteur veut ou attend
  - les points techniques/financiers/administratifs importants
  - les documents ou informations manquants
  - les incoherences detectees
- Utilise une structure lisible avec sections implicites ou explicites.
- Ne fais pas un simple copier-coller du mail.
- Si l'email est complexe, `detailed_summary` doit vraiment entrer dans le detail utile.

Consignes sur la priorite :
- `high` si le message implique une action rapide, un engagement formel, une offre, une piece manquante bloquante, ou une incoherence importante.
- `medium` si une reponse utile est attendue sans urgence immediate.
- `low` si le message est informatif, promotionnel ou n'appelle pas d'action rapide.

Consignes sur `category` :
- Choisis une seule categorie principale parmi cette liste :
  - Acheteur
  - Vendeur
  - Locataire
  - Proprietaire
  - Notaire
  - Huissier
  - Syndic
  - Travaux
  - Banque
  - Administratif
  - Commercial
  - Support
  - Autre
- Choisis la categorie la plus utile pour piloter la reponse.
- Si le message provient d'un huissier, d'une etude ou concerne une signification, une mise en demeure, une procedure ou une execution, choisis `Huissier`.

Consignes sur `tags` :
- `tags` sert a affiner l'analyse metier.
- Choisis entre 0 et 6 tags maximum parmi cette liste, uniquement s'ils sont vraiment pertinents :
  - Offre
  - Acquisition
  - Vente
  - Visite
  - Financement
  - Banque
  - Garantie
  - Notaire
  - Compromis
  - Bail
  - Loyers
  - Impaye
  - Contentieux
  - MiseEnDemeure
  - Procedure
  - Travaux
  - Devis
  - Planning
  - Sinistre
  - Assurance
  - Energie
  - Urbanisme
  - Administratif
  - DocumentManquant
  - PieceJointeManquante
  - Prioritaire
- Les tags peuvent se cumuler.
- Si le mail releve de plusieurs dimensions, utilise plusieurs tags pertinents.
- Si le mail mentionne des documents joints absents, ajoute `PieceJointeManquante`.
- Si le mail contient une demande documentaire incomplete ou des pieces attendues non visibles, ajoute `DocumentManquant`.
- Si le mail concerne un huissier, une mise en demeure ou une procedure, ajoute les tags adaptes comme `Contentieux`, `MiseEnDemeure` ou `Procedure` quand c'est pertinent.

Consignes sur `required_documents` :
- Liste uniquement les documents explicitement demandes a ton destinataire.
- N'inclus pas les documents que l'expediteur propose eventuellement d'envoyer plus tard "si necessaire".
- N'inclus pas non plus des photos, videos ou visuels simplement mentionnes comme disponibles sur une page externe.
- Si aucun document n'est demande, renvoie une liste vide.

Consignes sur `provided_documents` :
- Liste les documents que l'expediteur affirme avoir fournis ou joints.
- Base-toi sur le contenu du mail, mais distingue bien :
  - ce qui est annonce comme joint ou transmis avec le mail
  - ce qui est seulement disponible sur une page externe, un reseau social, un site, un drive ou sur demande
- Ne classe pas comme documents fournis les elements simplement accessibles sur Instagram, sur une page externe ou envoyables plus tard sur demande.
- Si rien n'est mentionne, renvoie une liste vide.

Consignes sur `attachment_analysis` :
- Mets une phrase courte utile sur l'etat des pieces jointes.
- Exemples :
  - "Aucune piece jointe detectee."
  - "Des pieces jointes sont presentes et devront etre analysees plus en detail."
  - "Le mail mentionne plusieurs documents, mais aucune piece jointe n'est presente."

Consignes sur `suggested_reply` :
- Redige une vraie reponse email professionnelle, directement envoyable apres validation humaine.
- La reponse doit etre cordiale, precise, credible et contextuelle.
- Elle doit respecter les standards d'un corps d'email professionnel :
  - formule d'appel adaptee
  - paragraphes clairs
  - ton naturel et poli
  - demande de clarification si necessaire
  - aucune affirmation factuellement fausse
  - aucune gratitude pour des documents non reellement recus
  - aucune phrase vague si une action precise est necessaire
- Si des documents annonces sont absents, la reponse doit le signaler explicitement et poliment.
- Si des photos, videos ou visuels sont mentionnes comme disponibles sur une page externe, la reponse doit le reconnaitre explicitement et ne pas pretendre qu'ils etaient attendus en piece jointe, sauf si le mail dit clairement qu'ils devaient etre joints.
- Si le dossier semble complet, la reponse peut accuser reception de facon professionnelle et annoncer la suite.
- La reponse doit s'adapter a la categorie retenue.
- La reponse doit aussi s'adapter a la combinaison categorie + tags.
- Par exemple, un mail `Travaux` + `Devis` + `Planning` doit susciter une reponse plus technique et operationnelle.
- Un mail `Acheteur` + `Financement` + `Offre` doit susciter une reponse orientee dossier, etapes et pieces.
- Si la categorie est `Huissier`, la reponse doit etre plus precise et prudente, proteger les droits du destinataire, demander les references, pieces, bases et delais utiles si necessaire, et formuler toute demande de clarification ou de temps complementaire de maniere licite, polie et professionnelle.
- Si la categorie est `Huissier`, tu ne dois jamais chercher a tromper, bloquer illicitement ou faire obstacle de mauvaise foi ; reste strictement factuel et professionnel.
- Si la categorie est `Huissier` ou si les tags montrent un contexte de recouvrement/contentieux (`Contentieux`, `MiseEnDemeure`, `Procedure`, `Impaye`), adopte un style plus formel, plus developpe et plus poli.
- Dans ce cas, la reponse doit ressembler a un courrier serieux de suivi de dossier :
  - accusé de réception du courrier ou de la mise en demeure
  - mention du dossier ou de la reference si elle existe
  - indication que la situation est en cours de traitement, d'examen interne ou de regularisation si cela reste factuellement prudent
  - formule de temporisation licite et professionnelle, sans mensonge ni obstruction
  - disponibilite pour tout renseignement complementaire
- Dans ce cas, evite les formulations trop seches ou trop courtes.
- Tu peux "broder" utilement sur la politesse, le cadre de traitement du dossier et la formulation professionnelle, mais jamais sur des faits inventes.
- Dans ce cas, ne demande pas l'envoi de contrats, factures, justificatifs, pieces ou documents complementaires, sauf si le mail recu demande explicitement quel document fournir.
- Dans ce cas, privilegie une reponse de type accuse de reception + suivi + regularisation prochaine, plutot qu'une contestation documentaire.
- Termine toujours par la signature exacte :
Samo Ferman

Consignes linguistiques :
- Detecte la langue principale de l'email recu.
- Redige la reponse dans cette meme langue principale.
- Si le mail melange plusieurs langues, utilise la langue dominante.

Si l'email est purement automatique, publicitaire ou ne merite pas de reponse utile, mets `should_reply` a false, mais garde une analyse exacte.

Email a analyser :
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
                    "content": (
                        "Tu es un analyste email senior tres rigoureux. "
                        "Tu produis uniquement du JSON valide et tu privilegies "
                        "la precision factuelle, la detection d'incoherences et la qualite redactionnelle."
                    ),
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
            summary=(payload.get("summary") or "").strip(),
            detailed_summary=(payload.get("detailed_summary") or payload.get("summary") or "").strip(),
            category=(payload.get("category") or "Autre").strip(),
            tags=[
                item.strip()
                for item in payload.get("tags", [])
                if isinstance(item, str) and item.strip()
            ],
            priority=(payload.get("priority") or "medium").strip(),
            suggested_reply=(payload.get("suggested_reply") or "").strip(),
            should_reply=bool(payload.get("should_reply", True)),
            required_documents=[
                item.strip()
                for item in payload.get("required_documents", [])
                if isinstance(item, str) and item.strip()
            ],
            provided_documents=[
                item.strip()
                for item in payload.get("provided_documents", [])
                if isinstance(item, str) and item.strip()
            ],
            attachment_analysis=(payload.get("attachment_analysis") or "").strip(),
        )
