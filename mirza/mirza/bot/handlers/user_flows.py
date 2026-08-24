"""User flows part 2: free trial, service detail + QR, extra volume, renew, phone verify, rules gate."""
from __future__ import annotations

import io
import secrets
from datetime import datetime, timedelta, timezone

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from mirza.db.models import BotSetting, Invoice, PanelServer, Product
from mirza.i18n.translate import t
from mirza.services.purchase import PurchaseError, PurchaseService
from mirza.services.wallet import WalletService

from ..fsm.states import BuyFlow

log = structlog.get_logger(__name__)
router = Router(name="user-flows-2")


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "∞"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ---------------------------------------------------------------- usertest
@router.callback_query(F.data == "usertest")
async def free_trial(cb: CallbackQuery, session, user):
    limit = (
        await session.execute(
            select(BotSetting.value).where(BotSetting.key == "limit_usertest_all")
        )
    ).scalar_one_or_none()
    limit = int(limit or 1)
    used = user.test_limit or 0
    if used >= limit:
        return await cb.message.answer(t("users.test.no_more"))
    panel_row = (
        await session.execute(
            select(PanelServer).where(PanelServer.allow_test.is_(True), PanelServer.enabled.is_(True))
        )
    ).scalars().first()
    if panel_row is None:
        return await cb.message.answer("⚠️ no test panels configured")
    vol = int(
        (await session.execute(select(BotSetting.value).where(BotSetting.key == "val_usertest"))).scalar_one() or 1
    )
    days = int(
        (await session.execute(select(BotSetting.value).where(BotSetting.key == "time_usertest"))).scalar_one() or 1
    )
    try:
        res = await PurchaseService(session).provision(
            user.id,
            custom={"location": panel_row.name, "volume_gb": vol,
                    "duration_days": days, "price": 0, "name": "usertest"},
            is_test=True,
        )
    except PurchaseError as e:
        return await cb.message.answer(t("users.buy.failed", reason=str(e)))
    user.test_limit = used + 1
    await session.commit()
    sub = res.panel_user.subscription_url
    kb = (InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Subscription", url=sub)]]) if sub else None)
    await cb.message.answer(t("users.test.ok", sub_url=sub or "-"), reply_markup=kb)


# ---------------------------------------------------------------- service detail + QR
@router.callback_query(F.data.startswith("svc:"))
async def service_detail(cb: CallbackQuery, session):
    inv_id = cb.data.split(":", 1)[1]
    inv = await session.get(Invoice, inv_id)
    if not inv:
        return await cb.answer(t("users.config.not_found"), show_alert=True)
    expires = "?"
    if inv.sold_at and inv.duration_days:
        exp = inv.sold_at + timedelta(days=inv.duration_days)
        expires = exp.strftime("%Y-%m-%d")
    cfg = inv.config_payload or {}
    text = t(
        "users.config.show",
        username=inv.service_username or "-",
        used="-", total=f"{inv.volume_gb or '∞'} GB", expires=expires,
    )
    kb_rows = []
    if cfg.get("subscription_url"):
        kb_rows.append([InlineKeyboardButton(text="🔗 Subscription", url=cfg["subscription_url"])])
    kb_rows.append([
        InlineKeyboardButton(text="♻️ Renew", callback_data=f"renew:{inv.id}"),
        InlineKeyboardButton(text="📊 Extra volume", callback_data=f"extra:{inv.id}"),
    ])
    kb_rows.append([InlineKeyboardButton(text="🧾 QR code", callback_data=f"qr:{inv.id}")])
    await cb.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data.startswith("qr:"))
async def send_qr(cb: CallbackQuery, session):
    inv_id = cb.data.split(":", 1)[1]
    inv = await session.get(Invoice, inv_id)
    sub = (inv.config_payload or {}).get("subscription_url") if inv else None
    if not sub:
        return await cb.answer(t("users.config.not_found"), show_alert=True)
    try:
        import qrcode  # optional dep

        img = qrcode.make(sub)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        await cb.message.answer_photo(
            BufferedInputFile(buf.getvalue(), filename="sub.png"),
            caption=t("users.config.qr_caption"),
        )
    except ImportError:
        await cb.message.answer(f"```\n{sub}\n```")
    await cb.answer()


# ---------------------------------------------------------------- renew / extra volume
RENEW_PRICES = {30: None}  # filled from settings at runtime


@router.callback_query(F.data.startswith("renew:"))
async def renew_menu(cb: CallbackQuery, state: FSMContext):
    inv_id = cb.data.split(":", 1)[1]
    await state.update_data(renew_inv=inv_id)
    await state.set_state(BuyFlow.custom_duration)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{d}d", callback_data=f"ren_days:{d}")] for d in (7, 14, 30, 60, 90)
        ]
    )
    await cb.message.answer(t("users.renew.ask_days"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("ren_days:"))
async def do_renew(cb: CallbackQuery, session, user):
    days = int(cb.data.split(":")[1])
    # price: reuse product-less wallet charge via setting price_per_day
    per_day = int((await session.execute(select(BotSetting.value).where(BotSetting.key == "price_per_day"))).scalar_one() or 1000)
    cost = days * per_day
    w = WalletService(session)
    if not await w.charge(user.id, cost, reason=f"renew:{days}d"):
        return await cb.message.answer(t("users.balance.insufficient"))
    # find most recent invoice of this user (simplification until svc picker lands)
    inv = (
        (await session.execute(select(Invoice).where(Invoice.user_id == user.id).order_by(Invoice.sold_at.desc())))
        .scalars().first()
    )
    try:
        updated = await PurchaseService(session).renew(inv.id, add_days=days)
    except PurchaseError as e:
        await w.add_balance(user.id, cost, reason="refund:renew_failed", actor_id=user.id)
        return await cb.message.answer(t("users.buy.failed", reason=str(e)))
    new_exp = (updated.sold_at + timedelta(days=updated.duration_days)).strftime("%Y-%m-%d") if updated.sold_at else "?"
    await cb.message.answer(t("users.renew.done", date=new_exp))


@router.callback_query(F.data.startswith("extra:"))
async def extra_volume(cb: CallbackQuery, session, user):
    inv_id = cb.data.split(":", 1)[1]
    inv = await session.get(Invoice, inv_id)
    if not inv:
        return await cb.answer("404", show_alert=True)
    per_gb = int((await session.execute(select(BotSetting.value).where(BotSetting.key == "Extra_volume"))).scalar_one() or 0)
    gb = 5
    cost = gb * per_gb
    w = WalletService(session)
    if not await w.charge(user.id, cost, reason=f"extra:{gb}gb"):
        return await cb.message.answer(t("users.balance.insufficient"))
    try:
        api, _row = await _panel_for(session, inv.panel_name)
        pu = await api.update_user(inv.service_username, volume_gb=(inv.volume_gb or 0) + gb)
        inv.volume_gb = (inv.volume_gb or 0) + gb
        inv.status = "active"
        await session.commit()
        await cb.message.answer(t("users.extra_volume.done", gb=gb))
    except Exception as e:
        await w.add_balance(user.id, cost, reason="refund:extra_failed", actor_id=user.id)
        await cb.message.answer(t("users.buy.failed", reason=str(e)))
    await cb.answer()


async def _panel_for(session, name):
    from mirza.core.registry import registry

    row = (await session.execute(select(PanelServer).where(PanelServer.name == name))).scalar_one()
    cls = registry.get("panel", row.plugin, row.revision)
    cfg = {"url": row.url, "username": row.username, "password": row.password,
           "sub_url_base": row.sub_url_base, "inbound_id": row.inbound_id}
    inst = cls(config=cfg)
    await inst.authenticate()
    return inst, row


# ---------------------------------------------------------------- phone & rules gates
@router.callback_query(F.data == "check_join")
async def check_join(cb: CallbackQuery, session, user):
    from .middleware import get_or_create_user  # noqa: F401

    await cb.answer(t("users.channel.confirmed"))


@router.message(F.contact)
async def phone_receive(message: Message, session, user):
    num = message.contact.phone_number.lstrip("+")
    iran_only = ((await session.execute(select(BotSetting.value).where(BotSetting.key == "iran_number"))).scalar_one() or "0") == "1"
    if iran_only and not num.startswith("98"):
        return await message.answer(t("users.phone.iran_only"))
    user.phone_number = num
    await session.commit()
    await message.answer("✅")


@router.callback_query(F.data == "accept_rules")
async def accept_rules(cb: CallbackQuery, session, user):
    user.rules_accepted = True
    await session.commit()
    await cb.message.answer(t("users.rules_ok"))
    await cb.answer()
