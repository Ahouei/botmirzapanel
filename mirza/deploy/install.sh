#!/usr/bin/env bash
# Mirza one-line installer (replaces legacy install.sh)
# Usage: curl -fsSL https://raw.githubusercontent.com/Ahouei/botmirzapanel/rewrite/python/mirza/deploy/install.sh | bash
set -euo pipefail

REPO="Ahouei/botmirzapanel"
BRANCH="rewrite/python"
DIR="/opt/mirza"

need_root() { [[ $EUID -eq 0 ]] || { echo "Run as root"; exit 1; }; }
need_root

apt-get update -qq
apt-get install -y -qq python3.12 python3.12-venv git nginx certbot python3-certbot-nginx postgresql-client

if [[ ! -d "$DIR/.git" ]]; then
  git clone --branch "$BRANCH" "https://github.com/${REPO}.git" "$DIR"
else
  git -C "$DIR" pull --ff-only
fi

python3.12 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -U pip -q
"$DIR/.venv/bin/pip" install -e "$DIR/mirza[dev]" -q
"$DIR/.venv/bin/pip" install "qrcode[pil]" -q

if [[ ! -f "$DIR/.env" ]]; then
  cp "$DIR/mirza/.env.example" "$DIR/.env"
  echo ">>> Edit $DIR/.env (BOT_TOKEN, ADMIN_IDS, DB password, WEBHOOK_SECRET) then re-run."
  exit 0
fi

# DB bootstrap (if postgres local)
if command -v psql >/dev/null 2>&1; then
  echo ">>> Run: sudo -u postgres psql -c \"CREATE USER mirza WITH PASSWORD '…'\" -c \"CREATE DATABASE mirza OWNER mirza\""
fi

"$DIR/.venv/bin/alembic" -c "$DIR/mirza/alembic.ini" upgrade head || true
cp "$DIR/mirza/deploy/mirza.service" /etc/systemd/system/mirza.service
systemctl daemon-reload
systemctl enable --now mirza.service
echo ">>> Mirza running. Check: systemctl status mirza && curl http://127.0.0.1:8080/healthz"
