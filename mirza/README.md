# Mirza Bot — Python Rewrite (6.0.0a1)

Full Python port of [botmirzapanel](https://github.com/mahdiMGF2/botmirzapanel) v5.9.11
as a **modular monolith** with a **plugin-first** architecture.

- **Stack:** Python 3.11+, aiogram 3, SQLAlchemy 2 async, PostgreSQL (SQLite for dev), APScheduler
- **Parity:** [`PARITY.md`](./PARITY.md) — line-by-line matrix vs the PHP original
- **Ops:** [`docs/OPS.md`](./docs/OPS.md) — deploy, backup, upgrade, troubleshooting
- **Dev:** [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) — local setup, adding plugins, testing

## Quick start (dev)

```bash
uv venv .venv && uv pip install -e ".[dev]"
export MIRZA_TG__BOT_TOKEN=123:abc MIRZA_TG__ADMIN_IDS='[172623365]'
export MIRZA_DB__DRIVER=sqlite+aiosqlite MIRZA_DB__NAME=mirza_dev
python -m mirza            # long polling (simplest)
python -m mirza --webhook  # webhook + /healthz + payment callbacks on :8080
# smoke (imports + pytest + ruff + alembic)
bash scripts/smoke.sh
```

## Production

```bash
# env first
cp .env.example .env && $EDITOR .env  # BOT_TOKEN, ADMIN_IDS, DB password, WEBHOOK_SECRET, BASE_URL

# Docker (recommended)
docker compose up -d --build
docker compose logs -f bot
curl http://127.0.0.1:8080/healthz | jq

# Systemd (bare metal)
sudo bash deploy/install.sh
systemctl status mirza
```

Legacy data migration:

```bash
python -m mirza.tools.import_legacy --mysql-dsn mysql+pymysql://u:p@host/dbname --pg-dsn postgresql+asyncpg://mirza:pass@localhost/mirza
```

## Extending (the point of the rewrite)

New panel type or a fork/revision of an existing one — one file, no core changes:

```python
# plugins/mypanel.py  <- drop-in, picked up at boot from MIRZA_PLUGIN_DIRS
from mirza.core.registry import register_panel
from mirza.panels.base import BasePanel, CreateSpec, PanelUser

@register_panel("mypanel", revision="v2")
class MyPanel(BasePanel):
    display_name = "MyPanel v2"
    async def authenticate(self): ...
    async def create_user(self, spec: CreateSpec) -> PanelUser: ...
    async def get_user(self, username): ...
    async def update_user(self, username, *, volume_gb=None, expires_at=None, enable=None): ...
    async def revoke_user(self, username): ...
    async def stats(self): ...
```

Same for payments: `@register_payment("mygw")` in `plugins/`.

Run `pytest` — the conformance suite validates every registered adapter; CI runs it on every push.

## Layout

```
mirza/
  core/       settings, plugin registry, logging
  db/         models (clean schema of 18 tables), session, alembic migrations
  panels/     BasePanel contract + 7 adapters (marzban, marzneshin, x-ui×2, s-ui, wgdashboard, mikrotik)
  payments/   gateway contract + nowpayments, aqayepardakht, card-to-card
  services/   purchase, wallet, referral
  bot/        aiogram handlers (user/admin), FSM states, middleware (block/channel/rules/phone)
  jobs/       scheduler replacing cron/*.php (expiry, volume, purge, probe, broadcast)
  i18n/       fa/en catalogs, runtime-overridable via TextOverride
  web/        /healthz + /readyz + payment callbacks
  tools/      legacy MySQL → PG importer
  deploy/     docker-compose, systemd, nginx, install.sh
docs/
  OPS.md, DEVELOPMENT.md
tests/        unit + adapter conformance + job/payment suites
plugins/      (gitignored) drop-ins
```

## Health & metrics

- `GET /healthz` — db, bot token, jobs, plugins, uptime
- `GET /readyz` — k8s readiness (db only)
- `GET /metrics` — Prometheus (invoices, users, payments, panel probe gauges)
- Structured JSON logs via `structlog`; `MIRZA_DEBUG=1` for console pretty mode
