# PARITY MATRIX — botmirzapanel v5.9.11 (PHP) → mirza-bot 6.0.0a1 (Python)

Legend: ✅ ported · 🔶 ported w/ improvement · 🆕 new feature · ⏳ scaffolded, logic stub pending

## Entry & boot
| PHP | Python | Status |
|---|---|---|
| index.php webhook entry + fastcgi_finish | `mirza/__main__.py` polling + aiohttp webhook | ✅ |
| config.php templated by install.sh | `.env` via pydantic-settings (`core/settings.py`) | 🔶 |
| table.php runtime CREATE/ALTER tables | Alembic migrations; dev auto-create | 🔶 |
| installer/index.php web installer | removed — single binary + env; setup wizard ⏳ | 🔶 |
| checktelegramip() Telegram-IP allowlist | webhook handler trusts Telegram secret path instead | 🔶 |

## User flows (index.php)
| Feature | Python home | Status |
|---|---|---|
| Registration + referral deep-link | handlers/user.py cmd_start + ReferralService.bind | ✅ |
| Forced channel join (+check button) | ChannelLockMiddleware | ✅ |
| Phone verification (all / Iran-only) | PhoneFlow states; regex validator ⏳ | 🔶 |
| Rules acceptance gate | User.rules_accepted flag; gate middleware ⏳ | ⏳ |
| Main menu + reply keyboards | user.py main_menu_kb (inline) | 🔶 |
| Buy: category → product → invoice → pay | BuyFlow + confirm_invoice/pay_invoice | ✅ |
| Custom volume/duration purchase | BuyFlow.custom_volume/custom_duration ⏳ | ⏳ |
| Free trial (usertest) w/ limits | callback `usertest` → PurchaseService(is_test) ⏳ | ⏳ |
| My services list + service detail + QR | services callback; QR via endroid→`qrcode` pkg ⏳ | ⏳ |
| Renew (remaining days credited) | PurchaseService.renew | ✅ |
| Extra volume top-up | extra_volume strings ready; flow ⏳ | ⏳ |
| Wallet balance / charge | WalletService (atomic) | ✅ |
| Top-up via NowPayments / Aqaye / card | payments/* + TopUpFlow | ✅ |
| Card-to-card receipt submit+approve | card.py gateway + admin receipt buttons ⏳ | 🔶 |
| Gift/discount codes | WalletService.redeem_gift_code | ✅ |
| Referral system + rewards | ReferralService + stats | ✅ |
| Support/help/FAQ texts | TextOverride table + help_entries | ⏳ |

## Admin flows (admin.php)
| Feature | Python home | Status |
|---|---|---|
| Admin login panel menu | admin.py /panel | ✅ |
| Multi-admin add/remove | Admins table + AdminFlows.add_admin ⏳ | ⏳ |
| Panel CRUD + connection test | adm:panels + adapter.authenticate as live test | 🔶 |
| Inbound/protocol selection per panel | PanelServer.inbound_id + extra JSONB | ✅ |
| Product CRUD + categories | products/categories tables; UI ⏳ | ⏳ |
| User search / block / balance edit | adm users flow | ✅ |
| Broadcast (immediate) | broadcast enqueue + worker | 🔶 |
| Forward-message broadcast ⏳ | queue stores full message payload | 🔶 |
| Sales/user/payment reports | adm:reports | ✅ |
| Discount/gift code creation | Discounts table; UI ⏳ | ⏳ |
| Sale % discounts per referrals tier | sale_discounts table; apply in pricing ⏳ | ⏳ |
| Settings editor (texts, limits) | text_overrides + settings KV | ⏳ |
| Manual cron management cmds | APScheduler replaces crontab entirely | 🆕 |
| shell_exec crontab edits | not needed — internal scheduler | 🆕 |

## Payments
| Legacy | Python | Status |
|---|---|---|
| payment/nowpayments (create+IPN verify) | nowpayments.py server-side re-verify | ✅ |
| payment/aqayepardakht (create+verify) | aqayepardakht.py | ✅ |
| cron/croncard.php card poll | receipts approved via buttons; no polling needed | 🔶 |
| DirectPayment() credit-on-paid | WalletService.mark_paid (idempotent) | ✅ |

## Cron jobs
| Legacy | Python (APScheduler) | Status |
|---|---|---|
| cronday.php expiry warnings | jobs/expiry.check_expiry_warnings daily 09:00 | ✅ |
| cronvolume.php traffic sync | sync_volumes every 2 min | ✅ |
| removeexpire.php purge after grace | purge_expired daily 03:30 | ✅ |
| sendmessage.php broadcast chunks | broadcast_worker every 30 s | ✅ |
| croncard.php card confirmations | event-driven approve buttons | 🔶 |
| configtest.php panel reachability | /healthz + panel test on save | 🔶 |

## Panels (ManagePanel)
| Adapter | Revisions | Status |
|---|---|---|
| Marzban | classic (token auth) | ✅ create/get/update/revoke/stats |
| Marzneshin | default (JWT) | ✅ |
| x-ui | 3x-ui + alireza (cookie login) | ✅ inbound client add/update/delete |
| s-ui | default | 🔶 create/revoke done; quota-edit limited by panel API |
| WGDashboard | default (API key) | 🔶 peer add/toggle/delete; GB quota via peer limit ⏳ |
| MikroTik | REST API (PPP secrets/profiles) | ✅ |

## Data model mapping (17 legacy tables)
user→users, admin→admins, channels→channel_locks, category→categories,
product→products, marzban_panel→panel_servers(+plugin/revision), invoice→invoices,
Payment_report→payment_reports, Discount→discounts, Giftcodeconsumed→gift_code_redemptions,
DiscountSell→sale_discounts, affiliates→referrals, setting→settings(KV),
textbot→text_overrides, PaySetting→gateway_settings, help→help_entries,
cancel_service→cancel_requests · NEW: audit_log

## New in the rewrite (no legacy equivalent)
- 🆕 Plugin registry with drop-in `plugins/` dir (add panel/gateway without touching core)
- 🆕 Adapter conformance test suite (tests/conformance)
- 🆕 Audit log for every wallet/admin action
- 🆕 Structured logging (JSON) + /healthz endpoint
- 🆕 Idempotent payment webhooks (double-callback safe)
- 🆕 i18n fa/en catalogs, admin-overridable at runtime
- 🆕 SQLite dev mode; PostgreSQL prod
