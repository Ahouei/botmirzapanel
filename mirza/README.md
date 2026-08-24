# Mirza Bot — Python Rewrite (6.0.0a1)

Full Python port of [botmirzapanel](https://github.com/mahdiMGF2/botmirzapanel) v5.9.11
as a **modular monolith** with a **plugin-first** architecture.

- **Stack:** Python 3.11+, aiogram 3, SQLAlchemy 2 async, PostgreSQL (SQLite for dev), APScheduler
- **Parity:** see [`PARITY.md`](./PARITY.md) for the line-by-line feature matrix vs the PHP original

## Quick start (dev)

```bash
uv venv .venv && uv pip install -e ".[dev]"
export MIRZA_TG__BOT_TOKEN=123:abc MIRZA_TG__ADMIN_IDS='[172623365]'
export MIRZA_DB__DRIVER=sqlite+aiosqlite MIRZA_DB__NAME=mirza_dev
python -m mirza            # long polling
python -m mirza --webhook  # webhook + /healthz + payment callbacks
```

## Production

```bash
docker build -t mirza-bot .
# env: MIRZA_DB__* , MIRZA_TG__* , MIRZA_WEB__*
```

Legacy data migration:

```bash
python -m mirza.tools.import_legacy --mysql-dsn mysql+pymysql://u:p@host/dbname
```

## Extending (the point of the rewrite)

New panel type or a fork/revision of an existing one:

```python
# plugins/mypanel.py  <- drop-in, no core changes, picked up at boot
from mirza.core.registry import register_panel
from mirza.panels.base import BasePanel, CreateSpec, PanelUser

@register_panel("mypanel", revision="v2")
class MyPanel(BasePanel):
    display_name = "MyPanel"
    async def authenticate(self): ...
    async def create_user(self, spec: CreateSpec) -> PanelUser: ...
    async def get_user(self, username): ...
    async def update_user(self, username, *, volume_gb=None, expires_at=None, enable=None): ...
    async def revoke_user(self, username): ...
    async def stats(self): ...
```

Run `pytest` — the conformance suite validates the contract; CI runs it on every push.

## Layout

```
mirza/
  core/      settings, plugin registry, logging
  db/        models (clean schema of all 17 legacy tables), session
  panels/    BasePanel contract + 7 adapters (marzban, marzneshin, x-ui×2, s-ui, wgdashboard, mikrotik)
  payments/  gateway contract + nowpayments, aqayepardakht, card-to-card
  services/  purchase, wallet, referral use-cases
  bot/       aiogram handlers (user/admin), FSM states, middleware
  jobs/      scheduler replacing cron/*.php (expiry, volume sync, broadcast)
  i18n/      fa/en catalogs, runtime-overridable
  web/       /healthz + payment callbacks
  tools/     legacy MySQL importer
tests/       unit + adapter conformance suite
```
