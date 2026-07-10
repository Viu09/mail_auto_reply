#!/usr/bin/env sh
set -eu

DATA_DIR="${DATA_DIR:-/app/data}"
SECRETS_DIR="${SECRETS_DIR:-$DATA_DIR/runtime_secrets}"
mkdir -p "$DATA_DIR" "$SECRETS_DIR" "$DATA_DIR/incoming_attachments" "$DATA_DIR/outbound_attachments"

export DATA_DIR SECRETS_DIR
# La materialisation des secrets Gmail (mono ou multi-comptes) est geree dans app/config.py.

# ROLE=worker  -> boucle d'ingestion Gmail + analyse Claude
# ROLE=api     -> API FastAPI qui sert le dashboard
ROLE="${ROLE:-worker}"

if [ "$ROLE" = "api" ]; then
  exec uvicorn app.api:app --host 0.0.0.0 --port "${PORT:-8000}"
else
  exec python -m app.worker
fi
