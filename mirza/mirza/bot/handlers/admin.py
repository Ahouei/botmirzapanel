"""Admin handlers: panel CRUD, user management, broadcast, receipts, settings."""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from mirza.core.registry import registry
from mirza.db.models import Admin, AuditLog, Invoice, PanelServer, PaymentReport, Product, User
from mirza.i18n.translate import t
from mirza.services.wallet import WalletService

from ..fsm.states import AdminFlows
from ..middleware import AdminFilter
from .user import main_menu_kb

log = structlog.get_logger(__name__)
router = Router(name="admin")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


@router.message(Command("panel"))
async def admin_panel(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("admin.panel_btns.users"), callback_data="adm:users"),
                InlineKeyboardButton(text=t("admin.panel_btns.panels"), callback_data="adm:panels"),
            ],
            [
                InlineKeyboardButton(text=t("admin.panel_btns.products"), callback_data="adm:products"),
                InlineKeyboardButton(text=t("admin.panel_btns.reports"), callback_data="adm:reports"),
            ],
            [
                InlineKeyboardButton(text=t("admin.panel_btns.broadcast"), callback_data="adm:broadcast"),
                InlineKeyboardButton(text=t("admin.panel_btns.payments"), callback_data="adm:payments"),
            ],
        ]
    )
    from mirza import __version__

    await message.answer(t("admin.login", version=__version__), reply_markup=kb)


# ---------------------------------------------------------------- panels mgmt
@router.callback_query(F.data == "adm:panels")
async def list_panels(cb: CallbackQuery, session):
    rows = (await session.execute(select(PanelServer))).scalars().all()
    lines = [f"• {r.name} [{r.plugin}/{r.revision}] {'✅' if r.enabled else '⛔'}" for r in rows]
    plugins = registry.list("panel")
    kb_rows = [[InlineKeyboardButton(text="➕ Add panel", callback_data="adm:panel:add")]]
    await cb.message.answer(
        "🔌 Panels:\n" + ("\n".join(lines) or "(none)") + f"\n\nAvailable plugins: {plugins}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
    await cb.answer()


@router.callback_query(F.data == "adm:panel:add")
async def panel_add_start(cb: CallbackQuery, state: FSMContext):
    plugins = registry.list("panel")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"{n}/{r}", callback_data=f"adm:panel:plugin:{n}:{r}")]
                         for _, n, r in plugins]
    )
    await cb.message.answer("Choose plugin:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:panel:plugin:"))
async def panel_add_plugin(cb: CallbackQuery, state: FSMContext):
    _, _, _, name, rev = cb.data.split(":")
    await state.set_state(AdminFlows.add_panel_url)
    await state.update_data(plugin=name, revision=rev)
    await cb.message.answer(f"URL of the {name}/{rev} panel:")
    await cb.answer()


@router.message(AdminFlows.add_panel_url)
async def panel_add_url(message: Message, state: FSMContext, session):
    data = await state.get_data()
    row = PanelServer(name=message.text.strip()[:40] + "-" + message.date.strftime("%H%M%S"),
                      url=message.text.strip(), plugin=data["plugin"], revision=data["revision"])
    session.add(row)
    await session.commit()
    await state.clear()
    await message.answer(t("admin.panel_mgmt.added"))


# ---------------------------------------------------------------- user mgmt
@router.callback_query(F.data == "adm:users")
async def users_menu(cb: CallbackQuery, state: FSMContext):
    total = None
    await state.set_state(AdminFlows.find_user)
    await cb.message.answer("Send a telegram user id to inspect:")
    await cb.answer()


@router.message(AdminFlows.find_user, F.text.regexp(r"^\d{3,15}$"))
async def find_user(message: Message, state: FSMContext, session):
    uid = int(message.text)
    await state.clear()
    u = await session.get(User, uid)
    if not u:
        return await message.answer(t("admin.user.not_found"))
    text = t("admin.user.found", id=u.id, balance=u.balance, status=u.status, refs=u.referral_count)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 +balance", callback_data=f"adm:bal:{u.id}"),
                InlineKeyboardButton(text="🚫 block", callback_data=f"adm:block:{u.id}"),
            ],
            [InlineKeyboardButton(text="✉️ message", callback_data=f"adm:msg:{u.id}")],
        ]
    )
    await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------- broadcast
@router.callback_query(F.data == "adm:broadcast")
async def broadcast_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.broadcast_text)
    await cb.message.answer(t("admin.broadcast.ask_text"))
    await cb.answer()


@router.message(AdminFlows.broadcast_text)
async def broadcast_text(message: Message, state: FSMContext, session, bot):
    await state.clear()
    ids = (await session.execute(select(User.id))).scalars().all()
    # hand off to jobs/broadcast.py worker via table queue (legacy sendmessage.php style)
    from mirza.jobs import broadcast as bc

    queued = await bc.enqueue(session, message.model_dump(exclude_none=True), ids)
    await message.answer(t("admin.broadcast.started", count=queued))


# ---------------------------------------------------------------- reports
@router.callback_query(F.data == "adm:reports")
async def reports(cb: CallbackQuery, session):
    users_n = (await session.execute(select(func.count()).select_from(User))).scalar()
    invs_n = (await session.execute(select(func.count()).select_from(Invoice))).scalar()
    sales = (await session.execute(select(func.coalesce(func.sum(Invoice.price), 0)))).scalar()
    paid = (
        await session.execute(
            select(func.coalesce(func.sum(PaymentReport.price), 0)).where(PaymentReport.payment_status == "paid")
        )
    ).scalar()
    await cb.message.answer(
        f"📊 Users: {users_n}\n🧾 Services sold: {invs_n}\n💵 Sales value: {sales:,}\n💳 Paid topups: {paid:,}"
    )
    await cb.answer()
