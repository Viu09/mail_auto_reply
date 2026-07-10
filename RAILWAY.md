# Deploiement Railway

Architecture cible sur Railway :

- **Postgres** (plugin Railway) — base partagee
- **Service `worker`** — boucle Gmail + analyse Claude (`ROLE=worker`)
- **Service `api`** — API FastAPI qui sert le dashboard (`ROLE=api`)
- **Dashboard Next.js** — deploye a part (Vercel ou service Railway), consomme l'API

Les deux services Python partent du **meme repo / meme Dockerfile**, seule la variable `ROLE` change.

## 1. Base de donnees

Ajoute le plugin **Postgres** dans le projet. Railway expose `DATABASE_URL`. Reference-la dans les deux services Python (variable partagee). Le code convertit automatiquement `postgres://` en `postgresql://`. Les tables sont creees au demarrage.

Un volume monte sur `/app/data` reste utile pour stocker les pieces jointes (entrantes/sortantes) et les secrets materialises.

## 2. Service worker

- Source : ce repo (Dockerfile detecte)
- Volume : `/app/data`
- Variables : voir liste ci-dessous + `ROLE=worker`
- Une seule instance (evite le double traitement Gmail)

## 3. Service api

- Source : ce repo (meme Dockerfile)
- Volume : `/app/data` (meme volume que le worker si possible, pour les pieces jointes)
- Variables : les memes + `ROLE=api`
- Railway fournit `PORT` automatiquement ; l'API ecoute dessus.

## Variables d'environnement

Communes aux deux services Python :

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL` (par defaut `claude-sonnet-5`)
- `ANTHROPIC_ENABLE_THINKING` (optionnel)
- `DATABASE_URL` (du plugin Postgres)
- `DATA_DIR=/app/data`
- `SECRETS_DIR=/app/data/runtime_secrets`
- `POLL_INTERVAL_SECONDS`
- `DEFAULT_REPLY_LANGUAGE`
- `DEFAULT_SIGNATURE`

Comptes Gmail (mono-compte legacy) :

- `GMAIL_CREDENTIALS_BASE64` (ou `GMAIL_CREDENTIALS_JSON`)
- `GMAIL_TOKEN_BASE64` (ou `GMAIL_TOKEN_JSON`)
- `GMAIL_QUERY`

Comptes Gmail (multi-comptes) :

- `MAIL_ACCOUNTS_JSON` ou `MAIL_ACCOUNTS_BASE64` : liste JSON des comptes (chacun avec son `token_base64` et son `label`). Voir la section « Comptes multiples » du README.

Dashboard / API :

- `DASHBOARD_EMAIL` : identifiant de connexion
- `DASHBOARD_PASSWORD` : mot de passe
- `SESSION_SECRET` : longue chaine aleatoire (signature des sessions)
- `FRONTEND_ORIGIN` : URL exacte du dashboard (pour le CORS), ex. `https://mon-dashboard.vercel.app`
- `ROLE` : `worker` sur le service worker, `api` sur le service api

## OAuth Gmail

Railway ne peut pas ouvrir de navigateur. Le bon flux :

1. faire l'autorisation Gmail localement
2. generer `token.json` (un par adresse)
3. injecter son contenu en base64 dans Railway (`GMAIL_TOKEN_BASE64` ou le `token_base64` du compte)

## Generer les variables base64

```bash
base64 -w 0 credentials.json
base64 -w 0 token.json
```

Si `-w 0` n'est pas supporte :

```bash
base64 credentials.json | tr -d '\n'
```

## Frontend (dashboard)

Le dossier `web/` (Next.js) se deploie separement (Vercel recommande) avec la variable :

- `NEXT_PUBLIC_API_URL` : URL publique du service `api` Railway

## Point d'attention

Ne lance qu'**une seule instance du worker**, sinon double traitement Gmail et doubles envois. L'API peut scaler, mais une instance suffit largement.
