# Railway Deployment

Ce projet peut tourner sur Railway comme `persistent service` toujours actif.

## Ce qu'il faut sur Railway

- 1 service Railway
- 1 seule instance
- 1 volume persistant monte sur `/app/data`
- les variables d'environnement habituelles
- `credentials.json` et `token.json` injectes via variables d'environnement

## Pourquoi un volume

Le bot stocke des donnees locales :

- base SQLite
- pieces jointes entrantes / sortantes
- eventuels secrets materialises a l'execution

Railway indique que le stockage local d'un service est ephemere. Pour persister les donnees entre redeploiements, il faut attacher un volume.

## Variables Railway recommandees

Variables metier :

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `ENABLE_TELEGRAM_NOTIFICATIONS`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_CHAT_IDS`
- `POLL_INTERVAL_SECONDS`
- `GMAIL_QUERY`
- `DEFAULT_REPLY_LANGUAGE`

Variables de stockage :

- `DATA_DIR=/app/data`
- `DATABASE_PATH=/app/data/app.db`
- `SECRETS_DIR=/app/data/runtime_secrets`
- `GMAIL_CREDENTIALS_PATH=/app/data/runtime_secrets/credentials.json`
- `GMAIL_TOKEN_PATH=/app/data/runtime_secrets/token.json`
- `ENABLE_DESKTOP_NOTIFICATIONS=false`

Variables secrets Gmail :

Choisis une des deux methodes pour chaque fichier :

1. JSON brut
- `GMAIL_CREDENTIALS_JSON`
- `GMAIL_TOKEN_JSON`

2. Base64
- `GMAIL_CREDENTIALS_BASE64`
- `GMAIL_TOKEN_BASE64`

La methode base64 est souvent plus simple sur Railway pour les fichiers JSON multilignes.

## Important pour Gmail OAuth

Railway ne pourra pas ouvrir un navigateur pour faire le consentement Google.

Le bon flux est :

1. faire l'autorisation Gmail localement
2. generer `token.json`
3. copier le contenu de `token.json` dans Railway

Tu peux faire pareil pour `credentials.json`.

## Deployment pas a pas

1. pousse le projet sur GitHub
2. cree un nouveau projet Railway
3. connecte le repo
4. Railway detectera le `Dockerfile`
5. ajoute un volume monte sur `/app/data`
6. ajoute les variables d'environnement
7. fixe le service sur une seule instance
8. deploie

## Generer les variables base64

Sous Linux / macOS :

```bash
base64 -w 0 credentials.json
base64 -w 0 token.json
```

Si `-w 0` n'est pas supporte :

```bash
base64 credentials.json | tr -d '\n'
base64 token.json | tr -d '\n'
```

## Commande de demarrage

Le `Dockerfile` appelle :

```bash
/app/entrypoint.sh
```

Ce script :

- cree les repertoires persistants
- materialise `credentials.json` et `token.json` depuis les variables d'environnement
- force `ENABLE_DESKTOP_NOTIFICATIONS=false`
- lance `python -m app.main`

## Point d'attention

Ne lance qu'une seule instance du worker, sinon tu risques :

- doublons Telegram
- double traitement Gmail
- doubles envois
