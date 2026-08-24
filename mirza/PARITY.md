# PARITY MATRIX — botmirzapanel v5.9.11 (PHP) → mirza-bot 6.0.0a1 (Python)

Legend: ✅ ported · 🔶 improved · 🆕 new

## Entry & boot
| PHP | Python | Status |
|---|---|---|
| index.php webhook entry + fastcgi_finish | `mirza/__main__.py` polling + aiohttp webhook | ✅ |
| config.php templated by install.sh | `.env` via pydantic-settings (`core/settings.py`) | 🔶 |
| table.php runtime CREATE/ALTER tables | Alembic migrations (initial clean schema) | 🔶 |
| installer/index.php web installer | removed — env + Docker; `tools/import_legacy.py` covers migration | 🔶 |
| checktelegramip() allowlist | webhook secret path + optional reverse-proxy IP allowlist | 🔶 |

## User flows
| Feature | Python | Status |
|---|---|---|
| Registration + referral deep-link | `handlers/user.py` cmd_start + `ReferralService.bind` | ✅ |
| Forced channel join (+check button) | `ChannelLockMiddleware` (DB key `channel_lock`) | ✅ |
| Phone verification (all / Iran-only) | contact handler + `is_valid_phone`, setting `get_number`/`iran_number` | ✅ |
| Rules acceptance gate | `RulesGateMiddleware` + `BotSetting require_rules` | ✅ |
| Main menu | inline keyboards (i18n fa/en) | ✅ |
| Buy: category → product → invoice → pay | `BuyFlow` + referral-tier discount | ✅ |
| Custom volume/duration order | `buy_custom` → `BuyFlow.custom_*` → auto panel pick | ✅ |
| Free trial (usertest) w/ limits | `usertest` callback + `limit_usertest_all`/`val_usertest`/`time_usertest` | ✅ |
| My services list + detail + live usage + QR | `svc:` + live panel fetch + `qrcode` optional | ✅ |
| Renew (remaining days credited) | `PurchaseService.renew` | ✅ |
| Extra volume top-up | `extra:` + panel `update_user` + wallet charge | ✅ |
| Wallet balance / charge | `WalletService` atomic | ✅ |
| Top-up via NowPayments / Aqaye / card-to-card | `payments/*` + `TopUpFlow` full gateway routing | ✅ |
| Card receipt photo → admin approve/reject | `TopUpFlow.card_receipt` + admin `rcpt:*` | ✅ |
| Gift/discount codes | `WalletService.redeem_gift_code` | ✅ |
| Referral tiers → auto % off | `SaleDiscount` applied at checkout | ✅ |
| Support/help/FAQ texts | `TextOverride` + `HelpEntry` | ✅ |

## Admin flows
| Feature | Python | Status |
|---|---|---|
| /panel menu | `admin.py` admin_panel | ✅ |
| Multi-admin add/remove + list | `Admin` table + `adm:admins` | ✅ |
| Panel CRUD (add URL→creds, edit URL/creds/inbound, toggle, delete) | `PanelServer` + registry `authenticate` test | ✅ |
| Panel live test + probe-all + hourly probe job | `adm:panel:test*` + `probe_panels` | ✅ |
| Inbound/profile per panel | `PanelServer.inbound_id` | ✅ |
| Product CRUD (add/edit price/vol/dur/loc/delete) | `adm:products` | ✅ |
| Category CRUD | `adm:cats` + product reassignment on delete | ✅ |
| User search / block / unblock / set balance / DM | `adm:users` + inline actions | ✅ |
| Broadcast text + forward modes (DB queue, 19/s) | `broadcast` + `forward_from_*` | ✅ |
| Reports (users, invoices, sales, paid) | `adm:reports` | ✅ |
| Gift code create (amount+limit) + list | `adm:gift:*` | ✅ |
| Sale discount tiers CRUD | `adm:sale:*` | ✅ |
| Settings KV editor | `adm:settings` + `adm:kv:set` | ✅ |
| Gateway settings editor (card number etc.) | `adm:gw:*` | ✅ |
| Texts editor + help entries list | `adm:texts` + `TextOverride` | ✅ |

## Payments
| Legacy | Python | Status |
|---|---|---|
| NowPayments create+IPN re-verify | `nowpayments.py` server-side `payment/{id}` check | ✅ |
| Aqayepardakht create+verify | `aqayepardakht.py` | ✅ |
| card poll cron | event-driven receipt photo + approve buttons | 🔶 |
| DirectPayment() idempotent | `WalletService.mark_paid` (double webhook safe) | ✅ |

## Cron jobs
| Legacy | Python APScheduler | Status |
|---|---|---|
| cronday.php expiry warnings | `check_expiry_warnings` daily 09:00 (deduped per day) | ✅ |
| cronvolume.php traffic sync | `sync_volumes` every 2 min (notifies on exhaust) | ✅ |
| removeexpire.php purge | `purge_expired` daily 03:30 (grace `removedayc`) | ✅ |
| sendmessage.php broadcast | `broadcast_worker` 30 s | ✅ |
| configtest.php panel test | `panel_probe` hourly + notify first admin on fail | ✅ |

## Panels
| Adapter | Revisions | Notes |
|---|---|---|
| Marzban | classic | token auth, sub URL fixup |
| Marzneshin | default | JWT → user API |
| x-ui | 3x-ui + alireza | cookie login, inbound client CRUD |
| s-ui | default | create/revoke; quota-edit panel-limited |
| WGDashboard | default | peer add/toggle/delete |
| MikroTik | rest | PPP secret + sessions |
| — | drop-in `plugins/` | new type/revision = one file |

## Data model (17 legacy + new)
`user→users`, `admin→admins`, `channels→channel_locks`, `category→categories`, `product→products`, `marzban_panel→panel_servers(+plugin/revision)`, `invoice→invoices`, `Payment_report→payment_reports`, `Discount→discounts`, `Giftcodeconsumed→gift_code_redemptions`, `DiscountSell→sale_discounts`, `affiliates→referrals`, `setting→settings(KV)`, `textbot→text_overrides`, `PaySetting→gateway_settings`, `help→help_entries`, `cancel_service→cancel_requests` · NEW: `audit_log`

## New (no legacy)
- Plugin registry with `plugins/` drop-ins
- Conformance test suite per adapter
- Audit log on wallet/admin actions
- Structured JSON logs + /healthz + /readyz
- Idempotent webhooks
- i18n fa/en catalogs (270+ strings)
- SQLite dev, PostgreSQL prod, Alembic migrations
