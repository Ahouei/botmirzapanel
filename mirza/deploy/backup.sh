#!/usr/bin/env bash
# Backup Mirza DB — works with both docker compose and bare-metal postgres
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATE="$(date +%F_%H%M)"
OUT="${1:-$ROOT/backups/mirza-$DATE.sql.gz}"
mkdir -p "$(dirname "$OUT")"

if docker compose -f "$ROOT/docker-compose.yml" ps db 2>/dev/null | grep -q "Up"; then
  echo "→ docker compose db dump → $OUT"
  docker compose -f "$ROOT/docker-compose.yml" exec -T db pg_dump -U mirza mirza | gzip > "$OUT"
elif command -v pg_dump >/dev/null 2>&1; then
  echo "→ pg_dump → $OUT"
  # reads PGPASSWORD from .env or env
  set -a; source "$ROOT/.env" 2>/dev/null || true; set +a
  PGPASSWORD="${MIRZA_DB__PASSWORD:-}" pg_dump -h "${MIRZA_DB__HOST:-localhost}" -U "${MIRZA_DB__USER:-mirza}" "${MIRZA_DB__NAME:-mirza}" | gzip > "$OUT"
else
  echo "No pg_dump nor compose db found"; exit 1
fi
echo "✅ $OUT ($(du -h "$OUT" | cut -f1))"
# keep last 7
ls -t "$ROOT"/backups/mirza-*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm -v
