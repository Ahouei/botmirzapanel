"""Broadcast worker. Legacy: cron/sendmessage.php (users.json + info files).

Improvement: DB-queued, resumable, rate-limited (~20 msg/s Telegram limit),
supports both text broadcasts and forwarded-message broadcasts,
progress reported to the triggering admin.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mirza.db.models import BotSetting

log = structlog.get_logger(__name__)
RATE = 19  # msgs per second ceiling


async def enqueue(session: AsyncSession, message_obj: dict[str, Any], user_ids: list[int]) -> int:
    # overwrite any pending broadcast (single queue, latest wins)
    existing = (await session.execute(select(BotSetting).where(BotSetting.key == "broadcast_queue"))).scalar_one_or_none()
    if existing:
        await session.delete(existing)
        await session.flush()
    payload = {"message": message_obj, "ids": user_ids, "sent": 0, "failed": 0, "created": datetime.now(UTC).isoformat()}
    session.add(BotSetting(key="broadcast_queue", value=json.dumps(payload, ensure_ascii=False)))
    await session.commit()
    return len(user_ids)


async def pop_queue(session: AsyncSession) -> dict | None:
    row = (await session.execute(select(BotSetting).where(BotSetting.key == "broadcast_queue"))).scalar_one_or_none()
    if not row or not row.value:
        return None
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return None


async def finish(session: AsyncSession) -> None:
    row = (await session.execute(select(BotSetting).where(BotSetting.key == "broadcast_queue"))).scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()


async def _send_one(bot, uid: int, msg: dict[str, Any]) -> bool:
    """Send either a text message or a forwarded message."""
    if "forward_from_chat_id" in msg and "forward_message_id" in msg:
        await bot.forward_message(chat_id=uid, from_chat_id=msg["forward_from_chat_id"], message_id=msg["forward_message_id"])
        return True
    # text broadcast — supports html_text / text / caption
    text = msg.get("html_text") or msg.get("text") or msg.get("caption") or ""
    if not text:
        # fallback: dump
        text = str(msg.get("text") or "")
    parse = "HTML" if msg.get("html_text") else None
    # handle photo/document if present (aiogram message dump includes photo array)
    if msg.get("photo"):
        photo = msg["photo"][-1]
        fid = photo.get("file_id") if isinstance(photo, dict) else getattr(photo, "file_id", None)
        if fid:
            await bot.send_photo(uid, fid, caption=text[:1024] if text else None, parse_mode=parse)
            return True
    await bot.send_message(uid, text, parse_mode=parse, disable_web_page_preview=True)
    return True


async def run_broadcast(session: AsyncSession, bot, admin_notify_id: int | None = None) -> None:
    job = await pop_queue(session)
    if not job:
        return
    sent = failed = 0
    ids: list[int] = job.get("ids") or []
    m: dict[str, Any] = job.get("message") or {}
    total = len(ids)
    for i in range(0, total, RATE):
        chunk = ids[i : i + RATE]
        results = await asyncio.gather(*[ _send_one_safe(bot, uid, m) for uid in chunk ], return_exceptions=True)
        sent += sum(1 for r in results if r is True)
        failed += sum(1 for r in results if r is not True)
        if admin_notify_id and total > 50 and (i // RATE) % 20 == 0:
            try:
                await bot.send_message(admin_notify_id, f"📨 Broadcast progress {sent}/{total} (failed {failed})")
            except Exception:
                pass
        await asyncio.sleep(1.05)
    await finish(session)
    log.info("broadcast.done", sent=sent, failed=failed, total=total)
    if admin_notify_id:
        try:
            from mirza.i18n.translate import t

            await bot.send_message(admin_notify_id, t("admin.broadcast.done", sent=sent, failed=failed))
        except Exception:
            try:
                await bot.send_message(admin_notify_id, f"✅ Broadcast done: {sent} sent, {failed} failed")
            except Exception:
                pass


async def _send_one_safe(bot, uid: int, msg: dict[str, Any]):
    try:
        await _send_one(bot, uid, msg)
        return True
    except Exception as e:
        log.debug("broadcast.send_failed", uid=uid, err=str(e)[:200])
        return e
