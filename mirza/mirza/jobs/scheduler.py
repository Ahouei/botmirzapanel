"""Background jobs (APScheduler). Legacy: the six cron/*.php files.

cronday.php      → expiry_warn (daily 09:00)
removeexpire.php → purge_expired (daily 03:30)
cronvolume.php   → volume_sync (every 2 min)
sendmessage.php  → broadcast_worker (every 30s)
configtest.php   → panel_probe (hourly)
croncard.php     → not needed (receipts are event-driven now)
"""
from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from mirza.db.models import Invoice

log = structlog.get_logger(__name__)
scheduler = AsyncIOScheduler(timezone="Asia/Tehran")


def setup_jobs(sessionmaker, bot, admin_notify_id: int | None) -> AsyncIOScheduler:
    from . import broadcast as bc
    from .expiry import check_expiry_warnings, probe_panels, purge_expired, sync_volumes

    async def _warn():
        async with sessionmaker() as s:
            await check_expiry_warnings(s, bot)

    async def _purge():
        async with sessionmaker() as s:
            await purge_expired(s, bot)

    async def _volume():
        async with sessionmaker() as s:
            await sync_volumes(s, bot)

    async def _bcast():
        async with sessionmaker() as s:
            await bc.run_broadcast(s, bot, admin_notify_id)

    async def _probe():
        async with sessionmaker() as s:
            await probe_panels(s, bot)

    # clear any prior jobs (idempotent re-setup)
    for j in list(scheduler.get_jobs()):
        scheduler.remove_job(j.id)

    scheduler.add_job(_volume, "interval", minutes=2, id="volume_sync", max_instances=1, coalesce=True)
    scheduler.add_job(_warn, "cron", hour=9, minute=0, id="expiry_warn", max_instances=1)
    scheduler.add_job(_purge, "cron", hour=3, minute=30, id="purge_expired", max_instances=1)
    scheduler.add_job(_bcast, "interval", seconds=30, id="broadcast_worker", max_instances=1, coalesce=True)
    scheduler.add_job(_probe, "interval", hours=1, id="panel_probe", max_instances=1)
    return scheduler


async def active_invoices(session):
    return ((await session.execute(select(Invoice).where(Invoice.status.in_(["active", "end_of_volume"])))).scalars().all())
