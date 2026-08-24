#!/usr/bin/env bash
# Restore Mirza DB
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IN="${1:?usage: $0 <dump.sql.gz>}"
if [[ ! -f "$IN" ]]; then echo "not found: $IN"; exit 1; fi

if docker compose -f "$ROOT/docker-compose.yml" ps db 2>/dev/null | grep -q "Up"; then
  echo "→ restore into compose db"
  gunzip -c "$IN" | docker compose -f "$ROOT/docker-compose.yml" exec -T db psql -U mirza mirza
else
  set -a; source "$ROOT/.env" 2>/dev/null || true; set +a
  echo "→ restore via psql"
  gunzip -c "$IN" | PGPASSWORD="${MIRZA_DB__PASSWORD:-}" psql -h "${MIRZA_DB__HOST:-localhost}" -U "${MIRZA_DB__USER:-mirza}" "${MIRZA_DB__NAME:-mirza}"
fi
echo "✅ restored from $IN"
