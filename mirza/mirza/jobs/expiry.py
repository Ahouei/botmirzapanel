"""Expiry lifecycle jobs.

Legacy mapping:
  cron/cronday.php     -> check_expiry_warnings (3-day & 1-day warnings)
  cron/cronvolume.php  -> sync_volumes (pull usage from panels, mark end_of_volume)
  cron/removeexpire.php-> purge_expired (delete/disable services past grace period)
  cron/configtest.php  -> probe_panels (reachability check, notify admins on failure)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select

from mirza.db.models import BotSetting, Invoice

log = structlog.get_logger(__name__)


async def _setting(session, key: str, default: str) -> str:
    v = (await session.execute(select(BotSetting.value).where(BotSetting.key == key))).scalar_one_or_none()
    return v if v is not None else default


async def _panel_api(session, invoice: Invoice):
    from mirza.core.registry import registry
    from mirza.db.models import PanelServer

    row = (await session.execute(select(PanelServer).where(PanelServer.name == invoice.panel_name))).scalar_one_or_none()
    if row is None:
        return None, None
    cls = registry.get("panel", row.plugin, row.revision)
    if not cls:
        return None, row
    cfg = {"url": row.url, "username": row.username, "password": row.password, "sub_url_base": row.sub_url_base, "inbound_id": row.inbound_id}
    cfg.update(row.extra or {})
    inst = cls(config=cfg)
    await inst.authenticate()
    return inst, row


async def check_expiry_warnings(session, bot) -> int:
    """Warn users N days before expiry (default 3 and 1)."""
    warned = 0
    warn_days = [int(x.strip()) for x in (await _setting(session, "warn_days", "3,1")).split(",") if x.strip().isdigit()]
    now = datetime.now(timezone.utc)
    invs = ((await session.execute(select(Invoice).where(Invoice.status == "active"))).scalars().all())
    for inv in invs:
        if not inv.sold_at or not inv.duration_days:
            continue
        # deduplicate: skip if already warned for this invoice today
        warn_key = f"warned:{inv.id}:{now.date().isoformat()}"
        already = (await session.execute(select(BotSetting.value).where(BotSetting.key == warn_key))).scalar_one_or_none()
        if already:
            continue
        expiry = inv.sold_at + timedelta(days=inv.duration_days)
        days_left = (expiry - now).days
        if days_left in warn_days:
            try:
                await bot.send_message(inv.user_id, f"⚠️ سرویس {inv.service_username} تا {days_left} روز دیگر منقضی می‌شود.\nبرای تمدید: /start → 🔧 My services → ♻️ Renew")
                session.add(BotSetting(key=warn_key, value="1"))
                warned += 1
            except Exception as e:
                log.warning("expiry.warn_failed", user=inv.user_id, err=str(e))
    if warned:
        await session.commit()
    return warned


async def sync_volumes(session, bot=None) -> dict[str, Any]:
    """Pull used traffic per service; flip status to end_of_volume when exhausted."""
    stats: dict[str, Any] = {"checked": 0, "exhausted": 0, "errors": 0}
    invs = ((await session.execute(select(Invoice).where(Invoice.status == "active"))).scalars().all())
    for inv in invs:
        stats["checked"] += 1
        api, row = await _panel_api(session, inv)
        if api is None or not inv.service_username:
            continue
        try:
            pu = await api.get_user(inv.service_username)
        except Exception as e:
            stats["errors"] += 1
            log.warning("volume.sync_failed", svc=inv.service_username, err=str(e))
            continue
        if pu is None:
            continue
        if pu.total_bytes and pu.used_bytes >= pu.total_bytes:
            inv.status = "end_of_volume"
            stats["exhausted"] += 1
            if bot:
                try:
                    await bot.send_message(inv.user_id, f"📊 حجم سرویس {inv.service_username} تمام شد.\nبرای تمدید: /start → 📊 Extra volume")
                except Exception:
                    pass
            else:
                log.info("volume.exhausted", invoice=inv.id, user=inv.user_id)
    await session.commit()
    return stats


async def purge_expired(session, bot=None) -> int:
    """After removedayc grace days past expiry, revoke the service."""
    grace = int(await _setting(session, "removedayc", "1"))
    now = datetime.now(timezone.utc)
    purged = 0
    invs = ((await session.execute(select(Invoice).where(Invoice.status.in_(["active", "end_of_time", "end_of_volume", "sendedwarn"])))).scalars().all())
    for inv in invs:
        if not inv.sold_at or not inv.duration_days:
            continue
        expiry = inv.sold_at + timedelta(days=inv.duration_days + grace)
        if expiry > now:
            continue
        api, row = await _panel_api(session, inv)
        if api is None:
            log.warning("purge.no_panel", invoice=inv.id, panel=inv.panel_name)
            continue
        try:
            await api.revoke_user(inv.service_username or "")
            inv.status = "expired"
            purged += 1
            if bot:
                try:
                    await bot.send_message(inv.user_id, f"⌛ سرویس {inv.service_username} منقضی و حذف شد.")
                except Exception:
                    pass
        except Exception as e:
            log.warning("purge.failed", svc=inv.service_username, err=str(e))
    await session.commit()
    return purged


async def probe_panels(session, bot=None) -> dict[str, Any]:
    """Legacy cron/configtest.php — periodically test each panel's reachability."""
    from mirza.core.registry import registry
    from mirza.db.models import PanelServer

    rows = (await session.execute(select(PanelServer))).scalars().all()
    results: dict[str, Any] = {"ok": [], "fail": []}
    for row in rows:
        cls = registry.get("panel", row.plugin, row.revision)
        if not cls:
            results["fail"].append(f"{row.name}: unknown plugin")
            continue
        try:
            cfg = {"url": row.url, "username": row.username, "password": row.password, "sub_url_base": row.sub_url_base, "inbound_id": row.inbound_id}
            cfg.update(row.extra or {})
            api = cls(config=cfg)
            await api.authenticate()
            await api.stats()
            results["ok"].append(row.name)
        except Exception as e:
            results["fail"].append(f"{row.name}: {e}")
            log.warning("panel.probe_failed", panel=row.name, err=str(e))
            if bot:
                # notify first admin on failure (rate-limited by BotSetting)
                key = f"panel_fail_notified:{row.name}"
                already = (await session.execute(select(BotSetting.value).where(BotSetting.key == key))).scalar_one_or_none()
                if not already:
                    try:
                        admin_id = None
                        from mirza.db.models import Admin
                        adm = (await session.execute(select(Admin.id))).scalars().first()
                        if adm:
                            admin_id = adm
                        if admin_id:
                            await bot.send_message(admin_id, f"⚠️ Panel {row.name} unreachable: {e}")
                        session.add(BotSetting(key=key, value=datetime.now(timezone.utc).isoformat()))
                        await session.commit()
                    except Exception:
                        pass
    return results
