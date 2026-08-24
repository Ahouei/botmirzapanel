"""Admin handlers: panel CRUD, user management, broadcast, receipts, settings."""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from mirza.core.registry import registry
from mirza.db.models import Invoice, PanelServer, PaymentReport, User
from mirza.i18n.translate import t

from ..fsm.states import AdminFlows
from ..middleware import AdminFilter

log = structlog.get_logger(__name__)
router = Router(name="admin")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


@router.message(Command("panel"))
@router.message(F.text == "/panel")
async def admin_panel(message: Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("admin.panel_btns.users"), callback_data="adm:users"), InlineKeyboardButton(text=t("admin.panel_btns.panels"), callback_data="adm:panels")],
            [InlineKeyboardButton(text=t("admin.panel_btns.products"), callback_data="adm:products"), InlineKeyboardButton(text=t("admin.panel_btns.reports"), callback_data="adm:reports")],
            [InlineKeyboardButton(text=t("admin.panel_btns.broadcast"), callback_data="adm:broadcast"), InlineKeyboardButton(text=t("admin.panel_btns.payments"), callback_data="adm:payments")],
            [InlineKeyboardButton(text="⚙️ Settings", callback_data="adm:settings"), InlineKeyboardButton(text="👑 Admins", callback_data="adm:admins")],
            [InlineKeyboardButton(text="📚 Texts", callback_data="adm:texts"), InlineKeyboardButton(text="📂 Categories", callback_data="adm:cats")],
        ]
    )
    from mirza import __version__

    await message.answer(t("admin.login", version=__version__), reply_markup=kb)


# compatibility: bare "panel" text (legacy)
@router.message(F.text.func(lambda v: v and v.strip().lower() == "panel"))
async def admin_panel_text(message: Message):
    await admin_panel(message)


# ---------------------------------------------------------------- panels mgmt
@router.callback_query(F.data == "adm:panels")
async def list_panels(cb: CallbackQuery, session):
    rows = (await session.execute(select(PanelServer))).scalars().all()
    lines = [f"• {r.id}: {r.name} [{r.plugin}/{r.revision}] {'✅' if r.enabled else '⛔'}" for r in rows]
    plugins = registry.list("panel")
    kb_rows = [
        [InlineKeyboardButton(text="➕ Add panel", callback_data="adm:panel:add")],
        [InlineKeyboardButton(text="🔍 Test all", callback_data="adm:panel:testall")],
    ]
    for r in rows:
        kb_rows.append([InlineKeyboardButton(text=f"✏️ {r.name}", callback_data=f"adm:panel:edit:{r.id}"), InlineKeyboardButton(text="🔍 Test", callback_data=f"adm:panel:test:{r.id}"), InlineKeyboardButton(text="🗑️ Del", callback_data=f"adm:panel:del:{r.id}")])
    await cb.message.answer("🔌 Panels:\n" + ("\n".join(lines) or "(none)") + f"\n\nPlugins: {', '.join(f'{n}/{r}' for _, n, r in plugins)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data == "adm:panel:add")
async def panel_add_start(cb: CallbackQuery, state: FSMContext):
    plugins = registry.list("panel")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{n}/{r}", callback_data=f"adm:panel:plugin:{n}:{r}")] for _, n, r in plugins])
    await cb.message.answer("Choose plugin:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:panel:plugin:"))
async def panel_add_plugin(cb: CallbackQuery, state: FSMContext):
    _, _, _, name, rev = cb.data.split(":", 4)
    await state.set_state(AdminFlows.add_panel_url)
    await state.update_data(plugin=name, revision=rev)
    await cb.message.answer(f"URL of the {name}/{rev} panel (e.g. https://panel.example.com:443):")
    await cb.answer()


@router.message(AdminFlows.add_panel_url, F.text.startswith("http"))
async def panel_add_url(message: Message, state: FSMContext, session):
    data = await state.get_data()
    url = message.text.strip().rstrip("/")
    # name derived from URL host
    import re
    host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].replace(".", "-")[:30]
    name = f"{host}-{message.date.strftime('%H%M%S')}"
    row = PanelServer(name=name, url=url, plugin=data["plugin"], revision=data["revision"])
    session.add(row)
    await session.commit()
    await state.update_data(panel_id=row.id, panel_name=name)
    await state.set_state(AdminFlows.add_panel_creds)
    await message.answer(f"✅ Panel `{name}` created.\nNow send credentials as: `username:password`\nOr just `username` if no password (e.g. WGDashboard api key in username).", parse_mode="Markdown")


@router.message(AdminFlows.add_panel_creds)
async def panel_add_creds(message: Message, state: FSMContext, session):
    data = await state.get_data()
    pid = data.get("panel_id")
    row = await session.get(PanelServer, pid) if pid else None
    if not row:
        await state.clear()
        await message.answer("Session expired, start again.")
        return
    parts = message.text.strip().split(":", 1)
    row.username = parts[0].strip()
    row.password = parts[1].strip() if len(parts) > 1 else ""
    # optional: inbound_id if provided as third segment username:password:inbound
    if row.password and ":" in row.password:
        pw, inbound = row.password.split(":", 1)
        row.password = pw
        row.inbound_id = inbound.strip()
    await session.commit()
    await state.clear()
    # test connection immediately
    try:
        cls = registry.get("panel", row.plugin, row.revision)
        cfg = {"url": row.url, "username": row.username, "password": row.password, "sub_url_base": row.sub_url_base, "inbound_id": row.inbound_id}
        api = cls(config=cfg)
        await api.authenticate()
        info = await api.stats()
        await message.answer(t("admin.panel_mgmt.tested_ok", info=str(info)[:500]))
    except Exception as e:
        await message.answer(t("admin.panel_mgmt.tested_fail", reason=str(e)[:500]))


@router.callback_query(F.data.startswith("adm:panel:test:"))
async def panel_test_one(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[-1])
    row = await session.get(PanelServer, pid)
    if not row:
        await cb.answer("not found", show_alert=True)
        return
    try:
        cls = registry.get("panel", row.plugin, row.revision)
        cfg = {"url": row.url, "username": row.username, "password": row.password, "sub_url_base": row.sub_url_base, "inbound_id": row.inbound_id}
        cfg.update(row.extra or {})
        api = cls(config=cfg)
        await api.authenticate()
        info = await api.stats()
        await cb.message.answer(f"✅ {row.name}: {info}")
    except Exception as e:
        await cb.message.answer(f"❌ {row.name}: {e}")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:panel:edit:"))
async def panel_edit_menu(cb: CallbackQuery, session, state: FSMContext):
    pid = int(cb.data.split(":")[-1])
    row = await session.get(PanelServer, pid)
    if not row:
        await cb.answer("not found", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ URL", callback_data=f"adm:panel:set:url:{pid}"), InlineKeyboardButton(text="✏️ Creds", callback_data=f"adm:panel:set:creds:{pid}")],
        [InlineKeyboardButton(text="✏️ Inbound", callback_data=f"adm:panel:set:inbound:{pid}"), InlineKeyboardButton(text="🔀 Toggle enabled", callback_data=f"adm:panel:toggle:{pid}")],
        [InlineKeyboardButton(text="🔙", callback_data="adm:panels")],
    ])
    await cb.message.answer(f"✏️ {row.name}\nURL: {row.url}\nPlugin: {row.plugin}/{row.revision}\nEnabled: {row.enabled}\nInbound: {row.inbound_id or '-'}", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:panel:set:"))
async def panel_set_field(cb: CallbackQuery, state: FSMContext):
    _, _, _, field, pid = cb.data.split(":", 4)
    await state.set_state(AdminFlows.edit_panel_field)
    await state.update_data(panel_id=int(pid), field=field)
    prompts = {"url": "Send new URL:", "creds": "Send username:password", "inbound": "Send inbound ID / profile name:"}
    await cb.message.answer(prompts.get(field, f"Send new {field}:"))
    await cb.answer()


@router.message(AdminFlows.edit_panel_field)
async def panel_apply_field(message: Message, state: FSMContext, session):
    data = await state.get_data()
    pid, field = data["panel_id"], data["field"]
    row = await session.get(PanelServer, pid)
    if not row:
        await state.clear()
        await message.answer("Not found")
        return
    val = message.text.strip()
    if field == "url":
        row.url = val.rstrip("/")
    elif field == "creds":
        parts = val.split(":", 1)
        row.username = parts[0]
        row.password = parts[1] if len(parts) > 1 else ""
    elif field == "inbound":
        row.inbound_id = val
    await session.commit()
    await state.clear()
    await message.answer("✅ Updated.")


@router.callback_query(F.data.startswith("adm:panel:toggle:"))
async def panel_toggle(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[-1])
    row = await session.get(PanelServer, pid)
    row.enabled = not row.enabled
    await session.commit()
    await cb.message.answer(f"{'✅ Enabled' if row.enabled else '⛔ Disabled'} {row.name}")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:panel:del:"))
async def panel_delete(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[-1])
    row = await session.get(PanelServer, pid)
    if row:
        await session.delete(row)
        await session.commit()
        await cb.message.answer(f"🗑️ Deleted {row.name}")
    await cb.answer()


@router.callback_query(F.data == "adm:panel:testall")
async def panel_test_all(cb: CallbackQuery, session):
    rows = (await session.execute(select(PanelServer))).scalars().all()
    for r in rows:
        try:
            cls = registry.get("panel", r.plugin, r.revision)
            cfg = {"url": r.url, "username": r.username, "password": r.password}
            api = cls(config=cfg)
            await api.authenticate()
            await cb.message.answer(f"✅ {r.name}")
        except Exception as e:
            await cb.message.answer(f"❌ {r.name}: {e}")
    await cb.answer()


# ---------------------------------------------------------------- user mgmt
@router.callback_query(F.data == "adm:users")
async def users_menu(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.find_user)
    await cb.message.answer("Send a telegram user id to inspect (or forward a message from them):")
    await cb.answer()


@router.message(AdminFlows.find_user, F.text.regexp(r"^\d{3,15}$"))
async def find_user(message: Message, state: FSMContext, session):
    uid = int(message.text.strip())
    await state.clear()
    u = await session.get(User, uid)
    if not u:
        return await message.answer(t("admin.user.not_found"))
    # count invoices
    inv_n = (await session.execute(select(func.count()).select_from(Invoice).where(Invoice.user_id == uid))).scalar() or 0
    text = t("admin.user.found", id=u.id, balance=f"{u.balance:,}", status=u.status, refs=u.referral_count) + f"\nServices: {inv_n}\nPhone: {u.phone_number or '-'}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Set balance", callback_data=f"adm:bal:{u.id}"), InlineKeyboardButton(text="🚫 Block", callback_data=f"adm:block:{u.id}")],
        [InlineKeyboardButton(text="✅ Unblock", callback_data=f"adm:unblock:{u.id}"), InlineKeyboardButton(text="✉️ Message", callback_data=f"adm:msg:{u.id}")],
        [InlineKeyboardButton(text="🔙", callback_data="adm:users")],
    ])
    await message.answer(text, reply_markup=kb)


@router.message(AdminFlows.find_user, F.forward_from)
async def find_user_forward(message: Message, state: FSMContext, session):
    uid = message.forward_from.id
    await state.clear()
    u = await session.get(User, uid)
    if not u:
        return await message.answer(t("admin.user.not_found"))
    await find_user(message, state, session)


@router.callback_query(F.data.startswith("adm:bal:"))
async def balance_prompt(cb: CallbackQuery, state: FSMContext):
    uid = cb.data.split(":")[-1]
    await state.set_state(AdminFlows.set_user_balance)
    await state.update_data(target_user=int(uid))
    await cb.message.answer(f"Send new balance for {uid} (number):")
    await cb.answer()


@router.message(AdminFlows.set_user_balance, F.text.regexp(r"^-?\d+$"))
async def set_balance(message: Message, state: FSMContext, session):
    data = await state.get_data()
    uid = data["target_user"]
    u = await session.get(User, uid)
    if not u:
        await state.clear()
        await message.answer("User not found")
        return
    u.balance = int(message.text.strip())
    await session.commit()
    await state.clear()
    await message.answer(f"✅ Balance set: {u.balance:,}")


@router.callback_query(F.data.startswith("adm:block:"))
async def block_prompt(cb: CallbackQuery, state: FSMContext):
    uid = cb.data.split(":")[-1]
    await state.set_state(AdminFlows.block_user_reason)
    await state.update_data(target_user=int(uid))
    await cb.message.answer("Send block reason (or '-' for no reason):")
    await cb.answer()


@router.message(AdminFlows.block_user_reason)
async def do_block(message: Message, state: FSMContext, session):
    data = await state.get_data()
    uid = data["target_user"]
    u = await session.get(User, uid)
    u.status = "Blocked"
    u.blocked_reason = message.text.strip() if message.text.strip() != "-" else None
    await session.commit()
    await state.clear()
    await message.answer(t("admin.user.blocked", reason=u.blocked_reason or "-"))


@router.callback_query(F.data.startswith("adm:unblock:"))
async def do_unblock(cb: CallbackQuery, session):
    uid = int(cb.data.split(":")[-1])
    u = await session.get(User, uid)
    if u:
        u.status = "Active"
        u.blocked_reason = None
        await session.commit()
        await cb.message.answer(t("admin.user.unblocked"))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:msg:"))
async def msg_prompt(cb: CallbackQuery, state: FSMContext):
    uid = cb.data.split(":")[-1]
    await state.set_state(AdminFlows.send_message_text)
    await state.update_data(target_user=int(uid))
    await cb.message.answer(f"Send message text for {uid} (supports HTML):")
    await cb.answer()


@router.message(AdminFlows.send_message_text)
async def send_direct(message: Message, state: FSMContext, session):
    data = await state.get_data()
    uid = data["target_user"]
    try:
        await message.bot.send_message(uid, message.text, parse_mode="HTML")
        await message.answer("✅ Sent.")
    except Exception as e:
        await message.answer(f"❌ Failed: {e}")
    await state.clear()


# ---------------------------------------------------------------- broadcast
@router.callback_query(F.data == "adm:broadcast")
async def broadcast_start(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Text broadcast", callback_data="adm:bcast:text")],
        [InlineKeyboardButton(text="↗️ Forward broadcast", callback_data="adm:bcast:fwd")],
    ])
    await cb.message.answer(t("admin.broadcast.ask_text") + "\nChoose mode:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:bcast:text")
async def bcast_text_mode(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.broadcast_text)
    await cb.message.answer("Send the broadcast text (HTML allowed):")
    await cb.answer()


@router.callback_query(F.data == "adm:bcast:fwd")
async def bcast_fwd_mode(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.broadcast_text)
    await state.update_data(forward=True)
    await cb.message.answer("Forward a message to broadcast it to all users:")
    await cb.answer()


@router.message(AdminFlows.broadcast_text)
async def broadcast_text(message: Message, state: FSMContext, session):
    data = await state.get_data()
    is_forward = data.get("forward")
    await state.clear()
    ids = (await session.execute(select(User.id).where(User.status != "Blocked"))).scalars().all()
    from mirza.jobs import broadcast as bc

    if is_forward:
        payload = {"forward_from_chat_id": message.chat.id, "forward_message_id": message.message_id}
    else:
        payload = message.model_dump(exclude_none=True)
        # strip bot internals
    queued = await bc.enqueue(session, payload, ids)
    await message.answer(t("admin.broadcast.started", count=queued))


# ---------------------------------------------------------------- reports
@router.callback_query(F.data == "adm:reports")
async def reports(cb: CallbackQuery, session):
    users_n = (await session.execute(select(func.count()).select_from(User))).scalar()
    invs_n = (await session.execute(select(func.count()).select_from(Invoice))).scalar()
    sales = (await session.execute(select(func.coalesce(func.sum(Invoice.price), 0)))).scalar()
    paid = (await session.execute(select(func.coalesce(func.sum(PaymentReport.price), 0)).where(PaymentReport.payment_status == "paid"))).scalar()
    active = (await session.execute(select(func.count()).select_from(Invoice).where(Invoice.status == "active"))).scalar()
    await cb.message.answer(f"📊 Users: {users_n}\n🧾 Services: {invs_n} (active {active})\n💵 Sales: {sales:,}\n💳 Paid topups: {paid:,}")
    await cb.answer()
