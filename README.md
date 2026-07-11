# Gmail AI Assistant

Assistant Gmail boosté à l'IA (Claude / Anthropic) avec un **dashboard web** pour trier, valider et envoyer les réponses. Il :

- surveille les nouveaux emails Gmail, sur plusieurs adresses en parallèle (séparées par un label de compte) ;
- analyse chaque email **en un seul appel Claude** (langue, résumé, synthèse détaillée, catégorie + tags, priorité, réponse suggérée, documents demandés/fournis), pièces jointes comprises (images et PDF en natif, DOCX/texte extraits) ;
- stocke tout en base (Postgres en production, SQLite en local) ;
- expose une **API** consommée par un **dashboard Next.js** : boîte de tri, fiche email, édition/validation de la réponse, envoi Gmail, upload de pièces jointes ;
- retravaille une réponse avec une consigne libre (« rends le ton plus formel… ») ;
- apprend du style des réponses validées (mémoire par compte) et tient compte de **l'historique du fil** ;
- permet des **règles d'automatisation** opt-in (auto-envoi / auto-rejet selon catégorie + priorité) ;
- évite de retraiter deux fois le même message, et **rattrape tout l'historique** progressivement (backfill).

### Fonctionnalités du dashboard

- **Catégories dynamiques** : dérivées automatiquement des emails présents (apparaissent/disparaissent seules), renommables/fusionnables, avec reclassement IA par lots des anciens « Autre ».
- **Documents** : les pièces jointes reçues sont stockées, catégorisées et résumables à la demande, avec aperçu intégré (image/PDF), recherche et téléchargement.
- **Multi-comptes** : ajout d'une adresse Gmail en un clic (« Se connecter avec Google », OAuth web), suppression, réglages par compte (signature, langue, requête), reconnexion.
- **Recherche plein texte**, **actions groupées** (envoyer / refuser / supprimer), **pagination**, **raccourcis clavier** (j/k/x/Échap).
- **Filtres expéditeur** déterministes (économie de coût IA), **modèles de réponse** réutilisables.
- **Statistiques** (volume, catégories, temps gagné) et **état d'ingestion**.
- **Thème clair/sombre**, notifications, pages d'erreur, **login multi-utilisateurs** avec anti-bruteforce.

### Sécurité

- Tokens Gmail **chiffrés au repos** (Fernet ; clé via `TOKEN_ENCRYPTION_KEY` ou dérivée de `SESSION_SECRET`).
- Secrets hors du dépôt (`.gitignore`), sessions signées, limitation des tentatives de connexion.

## Architecture

```
Worker (app/worker.py)  ── boucle Gmail → analyse Claude → DB (+ backfill historique)
API    (app/api.py)     ── FastAPI, sert le dashboard (login mono ou multi-utilisateur)
Web    (web/)           ── dashboard Next.js + Tailwind (Boîte, Documents, Statistiques, Paramètres)
DB                      ── Postgres (prod) / SQLite (local)
```

Le cœur métier est dans `app/services.py` (`EmailService`), réutilisé par le worker et l'API.

## Prérequis

- Python 3.11+
- un projet Google Cloud avec Gmail API activée
- des identifiants OAuth `Desktop app`
- une clé API Anthropic (Claude)
- Node.js 18+ (pour le dashboard `web/`)

## Installation (backend)

```bash
pip install -r requirements.txt
cp .env.example .env
```

Renseigne au minimum dans `.env` : `ANTHROPIC_API_KEY`, les secrets Gmail (`GMAIL_CREDENTIALS_BASE64` / `GMAIL_TOKEN_BASE64` ou `MAIL_ACCOUNTS_JSON`), et les identifiants du dashboard (`DASHBOARD_EMAIL`, `DASHBOARD_PASSWORD`, `SESSION_SECRET`).

## Configuration Google

1. crée un projet Google Cloud
2. active `Gmail API`
3. configure l'écran de consentement OAuth
4. crée des identifiants OAuth de type `Desktop app`
5. télécharge le JSON → `credentials.json`

Au premier lancement local, un navigateur autorise l'accès Gmail et le jeton est sauvegardé dans `token.json` (à injecter ensuite en base64 sur Railway).

Scopes : `gmail.modify`, `gmail.compose`.

## Lancement (local)

Deux processus, dans deux terminaux :

```bash
# 1. le worker (ingestion + analyse)
ROLE=worker python -m app.worker

# 2. l'API (dashboard)
ROLE=api uvicorn app.api:app --reload --port 8000
```

Puis le dashboard :

```bash
cd web
npm install
npm run dev
```

## Comptes multiples

Configure plusieurs adresses via `MAIL_ACCOUNTS_JSON` (ou `MAIL_ACCOUNTS_BASE64`) :

```json
[
  {"id":"pro","label":"PRO","gmail_query":"is:unread category:primary","token_base64":"<token.json en base64>"},
  {"id":"perso","label":"PERSO","gmail_query":"is:unread","reply_language":"fr","signature":"Samo Ferman","token_base64":"<token.json en base64>"}
]
```

Chaque compte accepte : `id`, `label`, `gmail_query`, `reply_language`, `signature`, ses identifiants OAuth (`credentials_json` / `credentials_base64` / `credentials_path`) et son jeton (`token_json` / `token_base64` / `token_path`). Sans identifiants OAuth propres, les identifiants partagés `GMAIL_CREDENTIALS_*` sont réutilisés.

Séparation : chaque adresse a sa propre file d'emails et sa propre mémoire de réponses (colonne `account_id`) ; le dashboard filtre par compte. Si `MAIL_ACCOUNTS_*` est vide, le mode compte unique (`GMAIL_*`) reste actif (compatibilité ascendante).

## Fonctionnement

Le worker supervise **l'historique déjà reçu et les futurs emails** correspondant à `gmail_query` (par défaut toute la boîte `category:primary`, pas seulement les non lus). Pour chaque email non encore traité, il :

1. récupère sujet, expéditeur, contenu et pièces jointes ;
2. transmet les pièces jointes à Claude (images/PDF natifs, DOCX/texte extraits) ;
3. demande à Claude, en un seul appel structuré, l'analyse complète et une réponse suggérée ;
4. enregistre le tout en base avec le statut `pending` ;
5. applique les règles d'automatisation (auto-envoi / auto-rejet) si définies.

La déduplication se fait en base (`gmail_id`), donc le worker **ne marque pas** les mails comme lus dans Gmail — un bouton **« Marquer comme lu »** est disponible dans le dashboard. Le rattrapage de l'historique est **étalé par lots** (`MAX_INGEST_PER_CYCLE` emails par cycle) pour maîtriser le coût Claude.

Depuis le dashboard, tu valides, édites ou retravailles la réponse, ajoutes des pièces jointes, puis envoies — l'email part par Gmail et le style est mémorisé pour affiner les futures réponses.

## API (résumé)

Toutes les routes (sauf `/auth/login` et `/health`) exigent un header `Authorization: Bearer <token>`.

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/auth/login` | connexion → jeton |
| `GET` | `/accounts` | comptes + compteurs |
| `GET` | `/emails` | liste filtrée (`account`, `status`, `category`, `priority`, `search`) |
| `GET` | `/emails/{id}` | fiche complète |
| `PATCH` | `/emails/{id}/reply` | éditer la réponse |
| `POST` | `/emails/{id}/refine` | retravailler avec Claude |
| `POST` | `/emails/{id}/send` | envoyer par Gmail |
| `POST` | `/emails/{id}/reject` | annuler |
| `POST` | `/emails/{id}/attachments` | ajouter une pièce jointe |
| `GET/POST/PATCH/DELETE` | `/rules` | règles d'automatisation |

## Variables utiles

- `ANTHROPIC_API_KEY` : clé API Anthropic (obligatoire)
- `ANTHROPIC_MODEL` : modèle Claude, par défaut `claude-sonnet-5`
- `DATABASE_URL` : Postgres en prod ; vide → SQLite local
- `DASHBOARD_EMAIL` / `DASHBOARD_PASSWORD` : login du dashboard
- `SESSION_SECRET` : signature des sessions (longue chaîne aléatoire)
- `FRONTEND_ORIGIN` : origine autorisée pour le CORS
- `MAIL_ACCOUNTS_JSON` / `MAIL_ACCOUNTS_BASE64` : liste des comptes email
- `DEFAULT_SIGNATURE` : signature par défaut des réponses
- `GMAIL_QUERY` : filtre Gmail (défaut `category:primary` = historique + futurs ; `is:unread category:primary` pour ne prendre que les nouveaux non lus ; `category:primary newer_than:30d` pour borner l'historique)
- `MAX_INGEST_PER_CYCLE` : nombre max d'emails analysés par cycle (défaut 20 ; étale le coût du rattrapage)
- `MAX_SCAN_PER_CYCLE` : nombre max d'emails scannés par cycle (défaut 500)
- `POLL_INTERVAL_SECONDS`, `DEFAULT_REPLY_LANGUAGE`
- `ROLE` : `worker` ou `api`

## Déploiement Railway

Voir [RAILWAY.md](RAILWAY.md) : plugin Postgres + un service `worker` + un service `api` (même Dockerfile, variable `ROLE`), et le dashboard `web/` déployé à part (Vercel).

## Qualité des réponses

- la réponse tient compte du message et des pièces jointes réellement présentes ;
- si un document annoncé comme fourni est absent, la réponse le signale poliment ;
- chaque email reste cordial, précis, et se termine par la signature du compte ;
- chaque mail reçoit une catégorie principale + des tags métier ; la réponse s'adapte à la combinaison catégorie + tags (ton plus formel pour un contexte huissier/recouvrement, etc.).
