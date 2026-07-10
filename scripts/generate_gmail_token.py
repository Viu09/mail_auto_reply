"""Genere un token.json Gmail et affiche sa version base64 pour Railway.

Usage (en local, avec un navigateur) :

    pip install google-auth-oauthlib google-auth
    python scripts/generate_gmail_token.py            # cherche credentials.json
    python scripts/generate_gmail_token.py mon_creds.json

Un navigateur s'ouvre, tu autorises l'acces Gmail, puis le script :
- ecrit token.json
- affiche la chaine a coller dans GMAIL_TOKEN_BASE64 (Railway).
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


def main() -> None:
    credentials_path = sys.argv[1] if len(sys.argv) > 1 else "credentials.json"
    if not Path(credentials_path).exists():
        print(f"Introuvable : {credentials_path}. Place ton credentials.json ici ou passe son chemin en argument.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    Path("token.json").write_text(creds.to_json(), encoding="utf-8")
    encoded = base64.b64encode(Path("token.json").read_bytes()).decode("utf-8")

    print("\n============================================================")
    print("token.json genere avec succes.")
    print("\nColle ceci dans la variable GMAIL_TOKEN_BASE64 (worker ET api) :\n")
    print(encoded)
    print("============================================================")


if __name__ == "__main__":
    main()
