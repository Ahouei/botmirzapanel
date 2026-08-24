"""Expiry lifecycle jobs.

Legacy mapping:
  cron/cronday.php     -> check_expiry_warnings (3-day & 1-day warnings)
  cron/cronvolume.php  -> sync_volumes (pull usage from panels, mark end_of_volume)
  cron/removeexpire.php-> purge_expired (delete/disable services past grace period)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select

from mirza.db.models import BotSetting, Invoice

log = structlog.get_logger(__name__)


async def _setting(session, key: str, default: str) -> str:
    v = (
        await session.execute(select(BotSetting.value).where(BotSetting.key == key))
    ).scalar_one_or_none()
    return v if v is not None else default


async def _panel_api(session, invoice: Invoice):
    from mirza.core.registry import registry
    from mirza.db.models import PanelServer

    row = (
        await session.execute(select(PanelServer).where(PanelServer.name == invoice.panel_name))
    ).scalar_one_or_none()
    if row is None:
        return None
    cls = registry.get("panel", row.plugin, row.revision)
    cfg = {"url": row.url, "username": row.username, "password": row.password,
           "sub_url_base": row.sub_url_base, "inbound_id": row.inbound_id}
    cfg.update(row.extra or {})
    inst = cls(config=cfg)
    await inst.authenticate()
    return inst


async def check_expiry_warnings(session, bot) -> int:
    """Warn users N days before expiry (default 3 and 1)."""
    warned = 0
    warn_days = [int(x) for x in (await _setting(session, "warn_days", "3,1")).split(",")]
    now = datetime.now(timezone.utc)
    invs = (
        (
            await session.execute(
                select(Invoice).where(Invoice.status.in_(["active"]))
            )
        )
        .scalars().all()
    )
    for inv in invs:
        if not inv.sold_at or not inv.duration_days:
            continue
        expiry = inv.sold_at + timedelta(days=inv.duration_days)
        days_left = (expiry - now).days
        if days_left in warn_days:
            try:
                await bot.send_message(
                    inv.user_id,
                    f"⚠️ سرویس {inv.service_username} تا {days_left} روز دیگر منقضی می‌شود.",
                )
                warned += 1
            except Exception as e:
                log.warning("expiry.warn_failed", user=inv.user_id, err=str(e))
    return warned


async def sync_volumes(session) -> dict[str, Any]:
    """Pull used traffic per service; flip status to end_of_volume when exhausted."""
    stats = {"checked": 0, "exhausted": 0}
    invs = (
        (
            await session.execute(select(Invoice).where(Invoice.status == "active"))
        )
        .scalars().all()
    )
    for inv in invs:
        stats["checked"] += 1
        api = await _panel_api(session, inv)
        if api is None or not inv.service_username:
            continue
        try:
            pu = await api.get_user(inv.service_username)
        except Exception as e:
            log.warning("volume.sync_failed", svc=inv.service_username, err=str(e))
            continue
        if pu is None:
            continue
        if pu.total_bytes and pu.used_bytes >= pu.total_bytes:
            inv.status = "end_of_volume"
            stats["exhausted"] += 1
            try:
                await bot_notify(session, inv.user_id,
                                 f"📊 حجم سرویس {inv.service_username} تمام شد.")
            except Exception:
                pass
    await session.commit()
    return stats


async def purge_expired(session, bot) -> int:
    """After removedayc grace days past expiry, revoke the service."""
    grace = int(await _setting(session, "removedayc", "1"))
    now = datetime.now(timezone.utc)
    purged = 0
    invs = (
        (
            await session.execute(
                select(Invoice).where(Invoice.status.in_(["active", "end_of_time", "end_of_volume"]))
            )
        )
        .scalars().all()
    )
    for inv in invs:
        if not inv.sold_at or not inv.duration_days:
            continue
        expiry = inv.sold_at + timedelta(days=inv.duration_days + grace)
        if expiry > now:
            continue
        api = await _panel_api(session, inv)
        if api is None:
            continue
        try:
            await api.revoke_user(inv.service_username or "")
            inv.status = "expired"
            purged += 1
        except Exception as e:
            log.warning("purge.failed", svc=inv.service_username, err=str(e))
    await session.commit()
    return purged


async def bot_notify(session, user_id: int, text: str) -> None:
    """Placeholder indirection so jobs stay testable without a live bot."""
    raise NotImplementedError("bot injected at runtime")
