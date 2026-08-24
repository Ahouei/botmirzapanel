"""Shared filters and middleware: registration, channel-lock, block-check, i18n."""
from __future__ import annotations

import secrets
from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject
from sqlalchemy import select

from mirza.db.models import ChannelLock, User

log = structlog.get_logger(__name__)

TELEGRAM_IPS_NOTE = "https://core.telegram.org/bots/webhooks#the-short-version"


async def get_or_create_user(session, tg_id: int, username: str | None) -> User:
    user = await session.get(User, tg_id)
    if user is None:
        user = User(
            id=tg_id,
            ref_code=secrets.token_hex(16),
            username=username or "none",
            step="none",
            status="Active",
        )
        session.add(user)
        await session.commit()
        log.info("user.created", user_id=tg_id)
    return user


class DbSessionMiddleware(BaseMiddleware):
    """One AsyncSession per update; injects 'session' and 'user' into handler data."""

    def __init__(self, sessionmaker):
        self.sm = sessionmaker

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        event_user = data.get("event_from_user")
        async with self.sm() as session:
            data["session"] = session
            if event_user and not event_user.is_bot:
                data["user"] = await get_or_create_user(session, event_user.id, event_user.username)
            return await handler(event, data)


class AdminFilter(Filter):
    async def __call__(self, event: TelegramObject, settings, user: User | None = None) -> bool:
        from mirza.core.settings import get_settings

        s = settings or get_settings()
        uid = getattr(user, "id", None) or (
            event.from_user.id if hasattr(event, "from_user") else None
        )
        return uid is not None and (uid in (s.telegram.admin_ids or []))


class ChannelLockMiddleware(BaseMiddleware):
    """Legacy forced-join. Skipped for admins; setting key channel_lock=off disables."""

    def __init__(self, bot_ref_getter):
        self.get_lock_channel = bot_ref_getter  # returns link str|None

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        user: User | None = data.get("user")
        link = await self.get_lock_channel(data.get("session"))
        msg: Message | None = event.message if isinstance(event, Message) else None
        cb: CallbackQuery | None = event if isinstance(event, CallbackQuery) else None
        if link and user and user.status != "Blocked":
            bot = data.get("bot")
            try:
                chat = await bot.get_chat_member(link.replace("@", ""), user.id)
                if chat.status in ("left", "kicked"):
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🔗 Join", url=f"https://t.me/{link.lstrip('@')}")],
                            [InlineKeyboardButton(text="✅ Check", callback_data="check_join")],
                        ]
                    )
                    text = "🔗 Please join our channel first."
                    if msg:
                        await msg.answer(text, reply_markup=kb)
                    elif cb:
                        await cb.answer()
                        await bot.send_message(user.id, text, reply_markup=kb)
                    return None  # swallow the update
            except Exception as e:  # channel unreachable -> fail open + log
                log.warning("channellock.skipped", err=str(e))
        return await handler(event, data)
