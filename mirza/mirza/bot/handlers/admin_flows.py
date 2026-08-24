"""Admin handlers part 2: products/categories, gift codes, settings editor, receipts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from mirza.db.models import Admin, BotSetting, Category, Discount, GatewaySetting, Invoice, Product, User
from mirza.i18n.translate import t
from mirza.services.wallet import WalletService

from ..fsm.states import AdminFlows
from ..middleware import AdminFilter

log = structlog.get_logger(__name__)
router = Router(name="admin-2")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


# ---------------------------------------------------------------- products
@router.callback_query(F.data == "adm:products")
async def list_products_admin(cb: CallbackQuery, session):
    prods = (await session.execute(select(Product))).scalars().all()
    lines = [f"• {p.name} — {p.price:,} / {p.volume_gb}GB / {p.duration_days}d [{p.location or '-'}]" for p in prods]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="➕ Add product", callback_data="adm:prod:add")]]
    )
    await cb.message.answer("📦 Products:\n" + ("\n".join(lines) or "(none)"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:prod:add")
async def prod_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.add_product_name)
    await cb.message.answer("Product name:")
    await cb.answer()


@router.message(AdminFlows.add_product_name)
async def prod_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text[:100])
    await state.set_state(AdminFlows.add_product_price)
    await message.answer("Price (toman):")


@router.message(AdminFlows.add_product_price, F.text.regexp(r"^\d+$"))
async def prod_price(message: Message, state: FSMContext):
    await state.update_data(price=int(message.text))
    await state.set_state(AdminFlows.add_product_volume)
    await message.answer("Volume GB:")


@router.message(AdminFlows.add_product_volume, F.text.regexp(r"^\d+$"))
async def prod_vol(message: Message, state: FSMContext, session):
    data = await state.get_data()
    p = Product(name=data["name"], price=data["price"], volume_gb=int(message.text), duration_days=30)
    session.add(p)
    await session.commit()
    await state.clear()
    await message.answer(t("admin.panel_mgmt.added"))


# ---------------------------------------------------------------- gift codes
@router.callback_query(F.data == "adm:payments")
async def payments_menu(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 New gift code", callback_data="adm:gift:new")],
            [InlineKeyboardButton(text="🏦 Gateway settings", callback_data="adm:gw:list")],
            [InlineKeyboardButton(text="🧾 Pending receipts", callback_data="adm:receipts")],
        ]
    )
    await cb.message.answer("💳 Payments:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:gift:new")
async def gift_new(cb: CallbackQuery, state: FSMContext, session):
    import secrets as _s

    code = "GIFT" + _s.token_hex(4).upper()
    session.add(Discount(code=code, amount=50_000, usage_limit=1))
    await session.commit()
    await cb.message.answer(f"🎁 Code: `{code}` — 50,000 (1 use)")
    await cb.answer()


@router.callback_query(F.data == "adm:receipts")
async def pending_receipts(cb: CallbackQuery, session, bot):
    from mirza.db.models import PaymentReport

    pend = (
        (
            await session.execute(
                select(PaymentReport).where(
                    PaymentReport.gateway == "card", PaymentReport.payment_status == "pending"
                )
            )
        )
        .scalars().all()
    )
    if not pend:
        return await cb.answer("(none)", show_alert=True)
    for r in pend:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="✅", callback_data=f"rcpt:ok:{r.order_id}"),
                InlineKeyboardButton(text="❌", callback_data=f"rcpt:no:{r.order_id}"),
            ]]
        )
        await cb.message.answer(f"🧾 {r.order_id}\nuser {r.user_id}: {r.price:,}", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("rcpt:ok:"))
async def receipt_approve(cb: CallbackQuery, session):
    order = cb.data.split(":", 2)[2]
    rep = await WalletService(session).mark_paid(order)
    if rep:
        await cb.message.edit_text(cb.message.text + "\n\n✅ approved")
    await cb.answer()


@router.callback_query(F.data.startswith("rcpt:no:"))
async def receipt_reject(cb: CallbackQuery, session):
    order = cb.data.split(":", 2)[2]
    rep = (await session.execute(select(PaymentReport).where(PaymentReport.order_id == order))).scalar_one_or_none()
    if rep and rep.payment_status != "paid":
        rep.payment_status = "canceled"
        await session.commit()
        await cb.message.edit_text(cb.message.text + "\n\n❌ rejected")
    await cb.answer()


# ---------------------------------------------------------------- settings KV editor
@router.callback_query(F.data == "adm:settings")
async def settings_menu(cb: CallbackQuery, session):
    rows = (await session.execute(select(BotSetting))).scalars().all()
    lines = [f"{r.key} = {r.value}" for r in rows] or ["(defaults active)"]
    await cb.message.answer("⚙️ Settings KV:\n" + "\n".join(lines[:30]))
    await cb.answer()


# ---------------------------------------------------------------- add admin
@router.message(AdminFlows.add_admin, F.text.regexp(r"^\d{3,15}$"))
async def add_admin_id(message: Message, state: FSMContext, session):
    uid = int(message.text)
    exists = await session.get(Admin, uid)
    if not exists:
        session.add(Admin(id=uid))
        await session.commit()
    await state.clear()
    await message.answer(f"✅ admin {uid} added")
