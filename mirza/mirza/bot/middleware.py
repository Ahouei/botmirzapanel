"""Shared filters and middleware: registration, channel-lock, block-check, i18n."""
from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.filters import Filter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from mirza.db.models import User

log = structlog.get_logger(__name__)

IRAN_MOBILE_RE = re.compile(r"^98\d{10}$")


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
        await session.refresh(user)
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
        async with self.sm() as session:
            data["session"] = session
            # aiogram stores the Telegram user on event.from_user, not data["event_from_user"]
            tg_user = getattr(event, "from_user", None)
            if tg_user and not tg_user.is_bot:
                data["user"] = await get_or_create_user(session, tg_user.id, tg_user.username)
            return await handler(event, data)


class SettingsMiddleware(BaseMiddleware):
    def __init__(self, settings):
        self.settings = settings

    async def __call__(self, handler, event, data):
        data["settings"] = self.settings
        return await handler(event, data)


class AdminFilter(Filter):
    async def __call__(self, event: TelegramObject, settings=None, user: User | None = None, **kwargs) -> bool:
        from mirza.core.settings import get_settings

        s = settings or get_settings()
        uid = getattr(user, "id", None)
        if uid is None:
            fu = getattr(event, "from_user", None)
            uid = getattr(fu, "id", None) if fu else None
        return uid is not None and uid in (s.telegram.admin_ids or [])


class BlockCheckMiddleware(BaseMiddleware):
    """Refuse all non-admin commands from blocked users."""

    async def __call__(self, handler, event, data):
        user: User | None = data.get("user")
        settings = data.get("settings")
        is_admin = False
        if settings and user:
            is_admin = user.id in (settings.telegram.admin_ids or [])
        if user and user.status == "Blocked" and not is_admin:
            msg = getattr(event, "message", None) or event
            # allow the blocked user to still receive the blocked notice
            bot = data.get("bot")
            if bot and user:
                try:
                    await bot.send_message(user.id, f"🚫 {user.blocked_reason or 'Blocked'}")
                except Exception:
                    pass
            return None
        return await handler(event, data)


class ChannelLockMiddleware(BaseMiddleware):
    """Legacy forced-join. Skipped for admins; setting key channel_lock=off disables."""

    def __init__(self, get_lock_channel):
        self.get_lock_channel = get_lock_channel

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        user: User | None = data.get("user")
        settings = data.get("settings")
        session = data.get("session")
        if not session or not user:
            return await handler(event, data)
        # admins bypass
        if settings and user.id in (settings.telegram.admin_ids or []):
            return await handler(event, data)
        if user.status == "Blocked":
            return await handler(event, data)
        link = await self.get_lock_channel(session)
        if not link:
            return await handler(event, data)
        bot = data.get("bot")
        if not bot:
            return await handler(event, data)
        try:
            chat_id = link.strip().replace("https://t.me/", "@").replace("t.me/", "@")
            if not chat_id.startswith("@"):
                chat_id = "@" + chat_id.lstrip("@")
            member = await bot.get_chat_member(chat_id, user.id)
            if member.status in ("left", "kicked"):
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔗 Join", url=f"https://t.me/{chat_id.lstrip('@')}")],
                        [InlineKeyboardButton(text="✅ Check", callback_data="check_join")],
                    ]
                )
                text = "🔗 Please join our channel first."
                # callback_query has no .answer with markup — send new message
                if isinstance(event, CallbackQuery):
                    await event.answer("Join required", show_alert=True)
                    await bot.send_message(user.id, text, reply_markup=kb)
                elif isinstance(event, Message):
                    await event.answer(text, reply_markup=kb)
                else:
                    await bot.send_message(user.id, text, reply_markup=kb)
                return None
        except Exception as e:
            log.warning("channellock.check_failed", err=str(e), link=link)
            # fail-open — don't block user if channel check itself errors
        return await handler(event, data)


class RulesGateMiddleware(BaseMiddleware):
    """If settings['require_rules'] == '1', force accept before any purchase."""

    async def __call__(self, handler, event, data):
        user: User | None = data.get("user")
        session = data.get("session")
        if user and session and not user.rules_accepted:
            from sqlalchemy import select as _select

            from mirza.db.models import BotSetting

            v = (await session.execute(_select(BotSetting.value).where(BotSetting.key == "require_rules"))).scalar_one_or_none()
            if v == "1":
                # allow only /start, rules accept, and support/help callbacks
                allowed_cb = {"accept_rules", "check_join", "support", "help", "faq"}
                cb_data = getattr(getattr(event, "data", None), "__str__", lambda: "")() if isinstance(event, CallbackQuery) else ""
                if isinstance(event, CallbackQuery) and event.data in allowed_cb:
                    return await handler(event, data)
                if isinstance(event, Message) and event.text and event.text.startswith("/start"):
                    return await handler(event, data)
                # otherwise prompt rules
                bot = data.get("bot")
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Accept rules", callback_data="accept_rules")]])
                target_id = user.id
                try:
                    if bot:
                        await bot.send_message(target_id, "♨️ Please accept the rules first.", reply_markup=kb)
                except Exception:
                    pass
                return None
        return await handler(event, data)


def is_valid_phone(text: str, iran_only: bool = False) -> bool:
    digits = re.sub(r"\D", "", text)
    if digits.startswith("0"):
        digits = "98" + digits[1:]
    if digits.startswith("+98"):
        digits = digits[1:]
    if iran_only:
        return bool(IRAN_MOBILE_RE.match(digits))
    return 7 <= len(digits) <= 15
