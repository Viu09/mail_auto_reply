#!/usr/bin/env sh
set -eu

APP_DIR="/app"
DATA_DIR="${DATA_DIR:-/app/data}"
SECRETS_DIR="${SECRETS_DIR:-$DATA_DIR/runtime_secrets}"

mkdir -p "$DATA_DIR" "$SECRETS_DIR" "$DATA_DIR/incoming_attachments" "$DATA_DIR/outbound_attachments"

export DATABASE_PATH="${DATABASE_PATH:-$DATA_DIR/app.db}"
export GMAIL_CREDENTIALS_PATH="${GMAIL_CREDENTIALS_PATH:-$SECRETS_DIR/credentials.json}"
export GMAIL_TOKEN_PATH="${GMAIL_TOKEN_PATH:-$SECRETS_DIR/token.json}"
export ENABLE_DESKTOP_NOTIFICATIONS="${ENABLE_DESKTOP_NOTIFICATIONS:-false}"

write_secret_file() {
  target_path="$1"
  raw_value="${2:-}"
  base64_value="${3:-}"

  if [ -n "$raw_value" ]; then
    printf "%s" "$raw_value" > "$target_path"
    return
  fi

  if [ -n "$base64_value" ]; then
    printf "%s" "$base64_value" | python -c "import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))" > "$target_path"
  fi
}

write_secret_file "$GMAIL_CREDENTIALS_PATH" "${GMAIL_CREDENTIALS_JSON:-}" "${GMAIL_CREDENTIALS_BASE64:-}"
write_secret_file "$GMAIL_TOKEN_PATH" "${GMAIL_TOKEN_JSON:-}" "${GMAIL_TOKEN_BASE64:-}"

exec python -m app.main
