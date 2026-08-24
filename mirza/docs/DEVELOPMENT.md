# DEVELOPMENT — Mirza Bot

## Local setup

```bash
uv venv .venv && uv pip install -e ".[dev]"
export MIRZA_TG__BOT_TOKEN=dummy  # for tests; real token for polling
export MIRZA_DB__DRIVER=sqlite+aiosqlite MIRZA_DB__NAME=:memory:
bash scripts/smoke.sh   # imports + pytest + ruff + alembic check
pytest -q               # 17 tests
```

For live polling against Telegram:

```bash
export MIRZA_TG__BOT_TOKEN=123:ABC MIRZA_TG__ADMIN_IDS='[172623365]'
export MIRZA_DB__DRIVER=sqlite+aiosqlite MIRZA_DB__NAME=mirza_dev
python -m mirza
```

## Adding a new VPN panel

1. Create `plugins/mypanel.py`:

```python
from mirza.core.registry import register_panel
from mirza.panels.base import BasePanel, CreateSpec, PanelUser, PanelError

@register_panel("mypanel", revision="v2")
class MyPanel(BasePanel):
    display_name = "MyPanel v2"
    async def authenticate(self): ...
    async def create_user(self, spec: CreateSpec) -> PanelUser: ...
    async def get_user(self, username): ...
    async def update_user(self, username, **kw): ...
    async def revoke_user(self, username): ...
    async def stats(self): ...
```

2. `pytest` — conformance suite in `tests/conformance/test_panel_contract.py` auto-discovers it.

3. In bot: `adm:panels → ➕ Add panel → mypanel/v2 → URL → user:pass`.

No core changes needed. Same pattern for gateways: `@register_payment("mygw")`.

## Adding a new gateway

```python
from mirza.core.registry import register_payment
from mirza.payments.base import BaseGateway, PaymentRequest, PaymentResult

@register_payment("mygw")
class MyGW(BaseGateway):
    async def create_payment(self, req: PaymentRequest) -> PaymentResult: ...
    async def verify_callback(self, payload: dict) -> tuple[str, bool]: ...
```

Store config in `gateway_settings` (`gateway=mygw, key=api_key`).

## DB & migrations

```bash
# edit mirza/db/models.py
MIRZA_DB_URL=sqlite+aiosqlite:////tmp/dev.db alembic revision --autogenerate -m "add foo"
MIRZA_DB_URL=sqlite+aiosqlite:////tmp/dev.db alembic upgrade head
```

Models use `JSONB().with_variant(JSON(), "sqlite")` so SQLite dev works.

## Testing

- `tests/unit/test_wallet.py` — balance, gift codes, idempotent pay
- `tests/unit/test_gates_jobs.py` — phone validation, broadcast queue, expiry dedup
- `tests/unit/test_payments.py` — card flow, referral discounts
- `tests/conformance/test_panel_contract.py` — contract for every registered panel (mock reference)
- `tests/unit/test_registry.py` — registry duplicates, builtin count

Add a test by dropping a file in `tests/unit/`.

## Lint & types

```bash
ruff check mirza
ruff check --fix mirza
mypy mirza --ignore-missing-imports
```

Ruff ignores: `BLE001, S110, S113, DTZ005, F841, RUF059, FURB162, SIM223` (see `pyproject.toml`).

## Jobs

APScheduler in `mirza/jobs/scheduler.py`:

- `volume_sync` 2 min, `broadcast_worker` 30 s, `panel_probe` 1 h, `expiry_warn` daily 09:00, `purge_expired` daily 03:30.

## Web

`mirza/web/health.py` → `/healthz`, `/readyz`, `/metrics` (Prometheus), payment callbacks `/payment/{gw}/callback` + legacy `/back.php`.

## i18n

`mirza/i18n/locales/fa.py` + `en.py` → `t("users.menu.buy")`. Admin overrides via `text_overrides` table.
