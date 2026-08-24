"""User-side handlers: start, main menu, buy flow, wallet, referral, gift, services."""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from mirza.core.registry import registry
from mirza.db.models import Category, Invoice, PaymentReport, Product
from mirza.i18n.translate import t
from mirza.services.purchase import PurchaseError, PurchaseService
from mirza.services.referral import ReferralService
from mirza.services.wallet import WalletService

from ..fsm.states import BuyFlow, GiftCodeFlow, TopUpFlow

log = structlog.get_logger(__name__)
router = Router(name="user")


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("users.menu.buy"), callback_data="buy")],
            [
                InlineKeyboardButton(text=t("users.menu.services"), callback_data="services"),
                InlineKeyboardButton(text=t("users.menu.test"), callback_data="usertest"),
            ],
            [
                InlineKeyboardButton(text=t("users.menu.wallet"), callback_data="wallet"),
                InlineKeyboardButton(text=t("users.menu.referral"), callback_data="referral"),
            ],
            [
                InlineKeyboardButton(text=t("users.menu.gift"), callback_data="gift"),
                InlineKeyboardButton(text=t("users.menu.support"), callback_data="support"),
            ],
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session, user, command: CommandObject | None = None):
    await state.clear()
    # deep-link referral binding (?start=<refcode>)
    if command and command.args and len(command.args) == 32:
        ref = ReferralService(session)
        referrer = await ref.resolve(command.args)
        if referrer:
            await ref.bind(user.id, referrer)
    await message.answer(
        t("users.start", name=message.from_user.first_name or "", shop="Mirza"),
        reply_markup=main_menu_kb(),
    )


# ---------------------------------------------------------------- buy flow
@router.callback_query(F.data == "buy")
async def buy_start(cb: CallbackQuery, session):
    cats = (await session.execute(select(Category))).scalars().all()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c.title, callback_data=f"cat:{c.id}")] for c in cats
        ]
        + [[InlineKeyboardButton(text=t("common.back") + " menu", callback_data="menu")]]
    )
    await cb.message.answer(t("users.buy.choose_category"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("cat:"))
async def list_products(cb: CallbackQuery, session):
    cid = int(cb.data.split(":")[1])
    prods = (
        (await session.execute(select(Product).where(Product.category_id == cid)))
        .scalars().all()
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{p.name} — {p.price:,}", callback_data=f"prod:{p.id}")]
            for p in prods
        ]
    )
    await cb.message.answer(t("users.buy.choose_product"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("prod:"))
async def confirm_invoice(cb: CallbackQuery, session, user):
    pid = int(cb.data.split(":")[1])
    p = await session.get(Product, pid)
    if not p:
        return await cb.answer("not found", show_alert=True)
    text = t(
        "users.buy.invoice",
        product=p.name, location=p.location or "-", volume=f"{p.volume_gb} GB",
        duration=f"{p.duration_days}d", price=f"{p.price:,}",
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Pay from wallet", callback_data=f"payinv:{pid}")],
            [InlineKeyboardButton(text="💳 Top up first", callback_data="wallet")],
        ]
    )
    await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("payinv:"))
async def pay_invoice(cb: CallbackQuery, session, user):
    pid = int(cb.data.split(":")[1])
    p = await session.get(Product, pid)
    wallet = WalletService(session)
    if not await wallet.charge(user.id, p.price, reason=f"buy:{p.name}"):
        return await cb.message.answer(t("users.balance.insufficient"))
    try:
        result = await PurchaseService(session).provision(user.id, product=p)
    except PurchaseError as e:
        await wallet.add_balance(user.id, p.price, reason="refund:provision_failed", actor_id=user.id)
        log.error("purchase.failed", user=user.id, err=str(e))
        return await cb.message.answer(t("users.buy.failed", reason=str(e)))
    sub = result.panel_user.subscription_url
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Subscription", url=sub)]]) if sub else None
    await cb.message.answer(t("users.buy.success", sub_url=sub or "(see links)"), reply_markup=kb)


# ---------------------------------------------------------------- services
@router.callback_query(F.data == "services")
async def my_services(cb: CallbackQuery, session, user):
    invs = (
        (
            await session.execute(
                select(Invoice).where(Invoice.user_id == user.id, Invoice.status != "deleted")
            )
        )
        .scalars().all()
    )
    kb_rows = []
    for i in invs:
        label = f"{i.product_name} ({i.service_username}) [{i.status}]"
        kb_rows.append([InlineKeyboardButton(text=label, callback_data=f"svc:{i.id}")])
    kb_rows.append([InlineKeyboardButton(text="« Menu", callback_data="menu")])
    await cb.message.answer("🔧 Your services:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


# ---------------------------------------------------------------- wallet/topup
@router.callback_query(F.data.in_({"wallet"}))
async def wallet_menu(cb: CallbackQuery, user, state: FSMContext):
    await cb.message.answer(t("users.balance.show", balance=f"{user.balance:,}"))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("users.menu.topup"), callback_data="topup")]]
    )
    await cb.message.answer("Choose:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "topup")
async def topup_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TopUpFlow.amount)
    await cb.message.answer("💰 Enter amount:")
    await cb.answer()


@router.message(TopUpFlow.amount, F.text.regexp(r"^\d{4,12}$"))
async def topup_amount(message: Message, state: FSMContext, session, user):
    amount = int(message.text)
    await state.update_data(amount=amount)
    await state.set_state(TopUpFlow.gateway)
    gws = registry.list("payment")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=n, callback_data=f"gw:{n}:{r}")] for _, n, r in gws]
    )
    await message.answer("Gateway:", reply_markup=kb)


# ---------------------------------------------------------------- referral/gift
@router.callback_query(F.data == "referral")
async def referral_menu(cb: CallbackQuery, session, user, settings):
    svc = ReferralService(session)
    stats = await svc.stats_for(user.id)
    link = f"https://t.me/{settings.telegram_bot_username or 'bot'}?start={user.ref_code}"
    await cb.message.answer(t("users.referral.menu", link=link, count=stats["count"], reward=stats["reward"]))
    await cb.answer()


@router.callback_query(F.data == "gift")
async def gift_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(GiftCodeFlow.code)
    await cb.message.answer(t("users.gift.ask_code"))
    await cb.answer()


@router.message(GiftCodeFlow.code)
async def gift_redeem(message: Message, state: FSMContext, session, user):
    ok, info = await WalletService(session).redeem_gift_code(user.id, message.text.strip())
    await state.clear()
    if ok:
        await message.answer(t("users.gift.result_ok", amount=info))
    else:
        await message.answer(f"❌ {info}")


@router.callback_query(F.data == "menu")
async def back_to_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("🏠", reply_markup=main_menu_kb())
    await cb.answer()
