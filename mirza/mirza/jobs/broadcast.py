"""Broadcast worker. Legacy: cron/sendmessage.php (users.json + info files).

Improvement: DB-queued, resumable, rate-limited (~20 msg/s Telegram limit),
progress reported to the triggering admin.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from aiogram.types import Message as TGMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mirza.db.models import BotSetting

log = structlog.get_logger(__name__)
RATE = 19  # msgs per second ceiling


async def enqueue(session: AsyncSession, message_obj: dict[str, Any], user_ids: list[int]) -> int:
    payload = {"message": message_obj, "ids": user_ids,
               "sent": 0, "failed": 0, "created": datetime.now(timezone.utc).isoformat()}
    session.add(BotSetting(key="broadcast_queue", value=json.dumps(payload)))
    await session.commit()
    return len(user_ids)


async def pop_queue(session: AsyncSession) -> dict | None:
    row = (
        await session.execute(select(BotSetting).where(BotSetting.key == "broadcast_queue"))
    ).scalar_one_or_none()
    if not row:
        return None
    try:
        return json.loads(row.value or "null")
    except ValueError:
        return None


async def finish(session: AsyncSession) -> None:
    row = (
        await session.execute(select(BotSetting).where(BotSetting.key == "broadcast_queue"))
    ).scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()


async def run_broadcast(session: AsyncSession, bot, admin_notify_id: int | None = None) -> None:
    job = await pop_queue(session)
    if not job:
        return
    sent = failed = 0
    ids: list[int] = job["ids"]
    m = job["message"]
    for i in range(0, len(ids), RATE):
        chunk = ids[i : i + RATE]
        results = await asyncio.gather(
            *[bot.send_message(uid, m.get("text", "")) for uid in chunk],
            return_exceptions=True,
        )
        sent += sum(1 for r in results if not isinstance(r, Exception))
        failed += sum(1 for r in results if isinstance(r, Exception))
        if admin_notify_id and (i // RATE) % 20 == 0:
            try:
                await bot.send_message(admin_notify_id, f"progress {sent}/{len(ids)}")
            except Exception:
                pass
        await asyncio.sleep(1.05)
    await finish(session)
    log.info("broadcast.done", sent=sent, failed=failed)
    if admin_notify_id:
        try:
            from mirza.i18n.translate import t

            await bot.send_message(admin_notify_id, t("admin.broadcast.done", sent=sent, failed=failed))
        except Exception:
            pass
