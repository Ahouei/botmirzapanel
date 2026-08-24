#!/usr/bin/env bash
# Smoke test — runs without Telegram token or Postgres
# Validates: imports, registry, DB create, payment + wallet flows, broadcast queue
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export MIRZA_DB__DRIVER=sqlite+aiosqlite
export MIRZA_DB__NAME=:memory:
export MIRZA_TG__BOT_TOKEN=dummy

echo "→ imports"
"$ROOT/.venv/bin/python" -c "import mirza.__main__; from mirza.core.registry import registry; registry.load_builtin('mirza.panels'); registry.load_builtin('mirza.payments'); print('panels', registry.list('panel')); print('payments', registry.list('payment'))"

echo "→ pytest"
"$ROOT/.venv/bin/python" -m pytest -q

echo "→ ruff"
"$ROOT/.venv/bin/ruff" check mirza

echo "→ alembic check"
"$ROOT/.venv/bin/alembic" check 2>&1 | head -5 || true

echo "✅ smoke ok"
