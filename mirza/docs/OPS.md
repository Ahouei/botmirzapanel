# OPS — Mirza Bot

## Deploy

### Docker (recommended)

```bash
cp .env.example .env && $EDITOR .env
# set: MIRZA_TG__BOT_TOKEN, MIRZA_TG__ADMIN_IDS, MIRZA_DB__PASSWORD, MIRZA_WEB__BASE_URL, MIRZA_WEB__WEBHOOK_SECRET
docker compose up -d --build
docker compose logs -f bot
# health
curl -s http://127.0.0.1:8080/healthz | jq
curl -s http://127.0.0.1:8080/readyz | jq
curl -s http://127.0.0.1:8080/metrics | head -20
```

Telegram webhook is set automatically on boot (`--webhook`). For polling, override: `command: python -m mirza`.

### Systemd (bare metal, no Docker)

```bash
sudo bash deploy/install.sh   # clones, venv, pip, alembic upgrade, enables service
sudo $EDITOR /opt/mirza/.env
sudo systemctl restart mirza
sudo systemctl status mirza -n 50
```

Nginx sample: `deploy/nginx.conf.example` → `/etc/nginx/sites-available/mirza` + `certbot --nginx -d bot.example.com`.

## Config

All via env, `MIRZA_` prefix, `__` for nesting:

| Var | Example | Notes |
|---|---|---|
| `MIRZA_TG__BOT_TOKEN` | `123:ABC` | from @BotFather |
| `MIRZA_TG__ADMIN_IDS` | `[172623365,123]` | JSON array |
| `MIRZA_DB__DRIVER` | `postgresql+asyncpg` | or `sqlite+aiosqlite` for dev |
| `MIRZA_DB__HOST/PORT/NAME/USER/PASSWORD` | | |
| `MIRZA_WEB__BASE_URL` | `https://bot.example.com` | for webhook + payment callbacks |
| `MIRZA_WEB__WEBHOOK_SECRET` | `random-32` | webhook path suffix |
| `MIRZA_PLUGIN_DIRS` | `plugins:/opt/mirza-plugins` | colon-separated |
| `MIRZA_DEBUG` | `false` | pretty logs when true |

## Upgrade

```bash
# Docker
git pull && docker compose up -d --build
# Systemd
git -C /opt/mirza pull --ff-only
/opt/mirza/.venv/bin/alembic -c /opt/mirza/mirza/alembic.ini upgrade head
sudo systemctl restart mirza
```

Rollback: `alembic downgrade -1` + `git checkout <prev-tag>` + restart.

## Backup & restore

```bash
# DB dump (compose)
docker compose exec db pg_dump -U mirza mirza | gzip > mirza-$(date +%F).sql.gz
# Bare metal
pg_dump -U mirza mirza | gzip > mirza-$(date +%F).sql.gz

# Restore
gunzip -c mirza-2026-01-01.sql.gz | docker compose exec -T db psql -U mirza mirza
# or
gunzip -c mirza-2026-01-01.sql.gz | psql -U mirza -h localhost mirza
```

Add to crontab: `0 3 * * * /opt/mirza/deploy/backup.sh` (created below).

## Legacy migration

```bash
python -m mirza.tools.import_legacy \
  --mysql-dsn mysql+pymysql://olduser:oldpass@oldhost/botdb \
  --pg-dsn postgresql+asyncpg://mirza:pass@localhost/mirza
# idempotent — re-run safe (skips existing PKs)
```

Mapping: `user→users`, `admin→admins`, `marzban_panel→panel_servers(+plugin/revision)`, etc. See `PARITY.md`.

## Troubleshooting

- `401 from Telegram` → `MIRZA_TG__BOT_TOKEN` wrong or bot deleted; check `healthz` `bot_configured`.
- `panel unreachable` → `adm:panels → 🔍 Test`; check `panel_servers` URL/creds; hourly `panel_probe` notifies first admin once per failing panel.
- `broadcast stuck` → `BotSetting key=broadcast_queue` holds the queue; delete it to cancel: `DELETE FROM settings WHERE key='broadcast_queue'`.
- `warn spam` → `check_expiry_warnings` dedups per invoice per day via `warned:<id>:<date>` key.
- Logs: `docker compose logs -f bot` or `journalctl -u mirza -f`; JSON when `MIRZA_DEBUG=false`.

## Security

- Webhook path includes `WEBHOOK_SECRET`; nginx should only expose 443.
- Card receipts: photos forwarded by `file_id`; bot never stores card numbers — only `GatewaySetting card.card_number`.
- `BotSetting` `channel_lock` can be `@channel` or `https://t.me/...`; empty = disabled.
