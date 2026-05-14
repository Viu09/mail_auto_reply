# Gmail AI Assistant

Ce projet est un MVP qui :

- surveille les nouveaux emails Gmail
- résume chaque email avec OpenAI
- propose une réponse automatique
- détecte la langue du mail et aligne la réponse sur cette langue
- affiche une notification locale optionnelle
- peut envoyer une vraie notification Telegram
- permet de valider ou refuser la reponse depuis Telegram
- permet d'ajouter des fichiers depuis Telegram avant envoi
- accepte les documents Telegram et les photos Telegram comme pieces jointes sortantes
- envoie un apercu Telegram des pieces jointes recues quand c'est possible
- analyse le contenu des images et des documents recus pour produire un compte rendu
- permet de retravailler la reponse avec une consigne libre depuis Telegram
- envoie ensuite la reponse finale par Gmail
- envoie sur Telegram un resume court et une synthese detaillee pour les emails complexes
- évite de retraiter plusieurs fois le même message

## Prérequis

- Python 3.11+
- un projet Google Cloud
- Gmail API activée
- des identifiants OAuth `Desktop app`
- une clé API OpenAI

## Installation

1. Crée un environnement virtuel.
2. Installe les dépendances :

```bash
pip install -r requirements.txt
```

3. Copie le fichier d'environnement :

```bash
cp .env.example .env
```

4. Dépose tes identifiants Google OAuth dans `credentials.json`.
5. Renseigne ta clé OpenAI dans `.env`.
6. Si tu veux Telegram, crée un bot et renseigne `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`.

## Configuration Google

Dans Google Cloud :

1. crée un projet
2. active `Gmail API`
3. configure l'écran de consentement OAuth
4. crée des identifiants OAuth de type `Desktop app`
5. télécharge le JSON et renomme-le en `credentials.json`

Au premier lancement, un navigateur s'ouvrira pour autoriser l'accès à Gmail. Le jeton sera sauvegardé dans `token.json`.

Scopes utilisés :

- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/gmail.compose`

## Lancement

```bash
python -m app.main
```

Le script tourne en boucle et vérifie Gmail toutes les `POLL_INTERVAL_SECONDS`.

## Deploiement Railway

Une preparation Railway est fournie avec :

- [Dockerfile](/home/viu/data_wsl/Projets_Personnels/Samo/Dockerfile)
- [entrypoint.sh](/home/viu/data_wsl/Projets_Personnels/Samo/entrypoint.sh)
- [RAILWAY.md](/home/viu/data_wsl/Projets_Personnels/Samo/RAILWAY.md)

Le deploiement Railway recommande repose sur :

- un service persistant unique
- un volume monte sur `/app/data`
- `credentials.json` et `token.json` injectes via variables d'environnement

## Fonctionnement

Pour chaque nouvel email correspondant à `GMAIL_QUERY`, le script :

1. récupère le sujet, l'expéditeur et le contenu texte
2. analyse le contenu des pieces jointes recues quand c'est possible
3. demande à OpenAI un résumé, un niveau de priorité, une réponse suggérée et les documents à fournir / déjà fournis
4. affiche une notification locale si activée
5. envoie une notification Telegram si activée
6. attend ta validation Telegram
7. récupère les fichiers envoyés au bot avec la légende `ATTACH <reference>`
8. envoie la réponse finale par Gmail avec les éventuelles pièces jointes
9. stocke le résultat dans SQLite

## Recommandation

Ce workflow envoie l'email final uniquement après validation explicite sur Telegram.

## Variables utiles

- `GMAIL_QUERY` : filtre Gmail, par exemple `is:unread category:primary`
- `POLL_INTERVAL_SECONDS` : fréquence de vérification
- `DEFAULT_REPLY_LANGUAGE` : langue de la réponse proposée
- `ENABLE_DESKTOP_NOTIFICATIONS` : `true` ou `false`, a desactiver sous WSL si besoin
- `ENABLE_TELEGRAM_NOTIFICATIONS` : `true` ou `false`
- `TELEGRAM_BOT_TOKEN` : token du bot Telegram
- `TELEGRAM_CHAT_ID` : identifiant du chat à notifier

## Configuration Telegram

1. ouvre Telegram et parle à `@BotFather`
2. lance `/newbot`
3. récupère le token du bot
4. envoie un message à ton bot
5. récupère ton `chat_id`

Pour récupérer ton `chat_id`, tu peux appeler :

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates"
```

Puis cherche la valeur `chat.id` dans la réponse JSON.

## Validation Telegram

Chaque notification Telegram contient une reference courte unique sur 3 caracteres, par exemple `K7M`.

- `OK abc` : envoie la réponse proposée
- `NON abc` : annule la réponse
- `EDIT abc rends le ton plus direct et demande les disponibilites` : retravaille la réponse avec OpenAI
- `DETAILS abc` : affiche la synthese detaillee du mail
- les consignes `EDIT` peuvent etre ecrites dans n'importe quelle langue, la reponse finale sera renvoyee dans la langue du mail
- `DOCS abc` : affiche l'analyse detaillee des pieces jointes du mail
- envoyer un document avec la légende `ATTACH abc` : ajoute ce fichier à l'email de réponse
- envoyer une photo avec la légende `ATTACH abc` : ajoute cette photo à l'email de réponse

## Langue de reponse

La langue principale du mail est detectee a la reception, puis memorisee pour tout le cycle :

- la reponse initiale est alignee sur cette langue
- une commande `EDIT` peut etre envoyee dans n'importe quelle langue
- l'email final est toujours reformule dans la langue du mail avant envoi

## Qualite des reponses

- les analyses de pieces jointes sont faites automatiquement, mais affichees seulement sur demande via `DOCS <reference>`
- les reponses tiennent compte du message et des pieces jointes analysees
- si un document est annonce comme fourni mais n'est pas detecte, la reponse doit le signaler poliment
- chaque email doit rester cordial, precis et se terminer par la signature `Samo Ferman`
- chaque mail recoit une categorie principale et peut recevoir plusieurs tags metier complementaires
- la reponse proposee s'adapte a la combinaison categorie + tags pour etre plus fine et plus contextuelle
