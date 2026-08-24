"""Admin handlers part 2: products/categories, gift codes, settings editor, receipts, texts, admins."""
from __future__ import annotations

import secrets

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from mirza.db.models import Admin, BotSetting, Category, Discount, GatewaySetting, HelpEntry, Invoice, Product, SaleDiscount, TextOverride, User
from mirza.i18n.translate import t

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
    lines = [f"• {p.id}: {p.name} — {p.price:,} / {p.volume_gb}GB / {p.duration_days}d [{p.location or '-'} cat:{p.category_id or '-'}]" for p in prods]
    kb_rows = [[InlineKeyboardButton(text="➕ Add product", callback_data="adm:prod:add")]]
    for p in prods:
        kb_rows.append([InlineKeyboardButton(text=f"✏️ {p.name[:20]}", callback_data=f"adm:prod:edit:{p.id}"), InlineKeyboardButton(text="🗑️", callback_data=f"adm:prod:del:{p.id}")])
    kb_rows.append([InlineKeyboardButton(text="🔙", callback_data="adm:products")])
    await cb.message.answer("📦 Products:\n" + ("\n".join(lines) or "(none)"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data == "adm:prod:add")
async def prod_add(cb: CallbackQuery, state: FSMContext, session):
    # show categories + panels for location choice later
    cats = (await session.execute(select(Category))).scalars().all()
    from mirza.db.models import PanelServer
    panels = (await session.execute(select(PanelServer.name))).scalars().all()
    hint = f"Cats: {', '.join(c.title for c in cats) or 'none (products uncategorized)'}\nPanels: {', '.join(panels) or 'none'}"
    await state.set_state(AdminFlows.add_product_name)
    await cb.message.answer(f"Product name:\n{hint}")
    await cb.answer()


@router.message(AdminFlows.add_product_name)
async def prod_name(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("Name too short, try again:")
        return
    await state.update_data(name=message.text.strip()[:100])
    await state.set_state(AdminFlows.add_product_price)
    await message.answer("Price (toman, number):")


@router.message(AdminFlows.add_product_price, F.text.regexp(r"^\d+$"))
async def prod_price(message: Message, state: FSMContext):
    await state.update_data(price=int(message.text))
    await state.set_state(AdminFlows.add_product_volume)
    await message.answer("Volume GB (number):")


@router.message(AdminFlows.add_product_volume, F.text.regexp(r"^\d+$"))
async def prod_vol(message: Message, state: FSMContext):
    await state.update_data(volume=int(message.text))
    await state.set_state(AdminFlows.add_product_duration)
    await message.answer("Duration days (number, e.g. 30):")


@router.message(AdminFlows.add_product_duration, F.text.regexp(r"^\d+$"))
async def prod_dur(message: Message, state: FSMContext):
    await state.update_data(duration=int(message.text))
    await state.set_state(AdminFlows.add_product_location)
    await message.answer("Location (panel name, or '-' for any):")


@router.message(AdminFlows.add_product_location)
async def prod_loc(message: Message, state: FSMContext, session):
    data = await state.get_data()
    loc = message.text.strip()
    loc = None if loc == "-" else loc
    p = Product(name=data["name"], price=data["price"], volume_gb=data["volume"], duration_days=data["duration"], location=loc)
    session.add(p)
    await session.commit()
    await state.clear()
    await message.answer(f"✅ Product `{p.name}` added (id {p.id})", parse_mode="Markdown")


@router.callback_query(F.data.startswith("adm:prod:edit:"))
async def prod_edit_menu(cb: CallbackQuery, session, state: FSMContext):
    pid = int(cb.data.split(":")[-1])
    p = await session.get(Product, pid)
    if not p:
        await cb.answer("not found", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Price", callback_data=f"adm:prod:set:price:{pid}"), InlineKeyboardButton(text="✏️ Volume", callback_data=f"adm:prod:set:volume:{pid}")],
        [InlineKeyboardButton(text="✏️ Duration", callback_data=f"adm:prod:set:duration:{pid}"), InlineKeyboardButton(text="✏️ Location", callback_data=f"adm:prod:set:location:{pid}")],
        [InlineKeyboardButton(text="🔙", callback_data="adm:products")],
    ])
    await cb.message.answer(f"✏️ {p.name}\nPrice: {p.price:,}\nVol: {p.volume_gb}GB\nDur: {p.duration_days}d\nLoc: {p.location or '-'}", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:prod:set:"))
async def prod_set_field(cb: CallbackQuery, state: FSMContext):
    _, _, _, field, pid = cb.data.split(":", 4)
    await state.set_state(AdminFlows.edit_panel_field)
    await state.update_data(prod_id=int(pid), prod_field=field)
    await cb.message.answer(f"Send new {field}:")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:prod:del:"))
async def prod_del(cb: CallbackQuery, session):
    pid = int(cb.data.split(":")[-1])
    p = await session.get(Product, pid)
    if p:
        await session.delete(p)
        await session.commit()
        await cb.message.answer(f"🗑️ Deleted {p.name}")
    await cb.answer()


# edit handler shares AdminFlows.edit_panel_field but with prod_ prefix - disambiguate in message handler below
@router.message(AdminFlows.edit_panel_field)
async def prod_apply_field(message: Message, state: FSMContext, session):
    data = await state.get_data()
    # product edit path
    if "prod_id" in data:
        pid, field = data["prod_id"], data["prod_field"]
        p = await session.get(Product, pid)
        if not p:
            await state.clear()
            await message.answer("Not found")
            return
        val = message.text.strip()
        if field == "price":
            p.price = int(val)
        elif field == "volume":
            p.volume_gb = int(val)
        elif field == "duration":
            p.duration_days = int(val)
        elif field == "location":
            p.location = None if val == "-" else val
        await session.commit()
        await state.clear()
        await message.answer("✅ Product updated.")
        return
    # panel edit path (handled in admin.py) — fallback
    if "panel_id" in data:
        from mirza.db.models import PanelServer as PS
        pid, field = data["panel_id"], data["field"]
        row = await session.get(PS, pid)
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
        await message.answer("✅ Panel updated.")
        return
    await state.clear()


# ---------------------------------------------------------------- categories
@router.callback_query(F.data == "adm:cats")
async def list_cats(cb: CallbackQuery, session):
    cats = (await session.execute(select(Category))).scalars().all()
    lines = [f"• {c.id}: {c.title}" for c in cats]
    kb_rows = [[InlineKeyboardButton(text="➕ Add category", callback_data="adm:cat:add")]]
    for c in cats:
        kb_rows.append([InlineKeyboardButton(text=f"✏️ {c.title}", callback_data=f"adm:cat:edit:{c.id}"), InlineKeyboardButton(text="🗑️", callback_data=f"adm:cat:del:{c.id}")])
    await cb.message.answer("📂 Categories:\n" + ("\n".join(lines) or "(none)"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@router.callback_query(F.data == "adm:cat:add")
async def cat_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.add_category_name)
    await cb.message.answer("Category title:")
    await cb.answer()


@router.message(AdminFlows.add_category_name)
async def cat_create(message: Message, state: FSMContext, session):
    title = message.text.strip()[:100]
    session.add(Category(title=title))
    await session.commit()
    await state.clear()
    await message.answer(f"✅ Category `{title}` added", parse_mode="Markdown")


@router.callback_query(F.data.startswith("adm:cat:edit:"))
async def cat_edit(cb: CallbackQuery, state: FSMContext):
    cid = int(cb.data.split(":")[-1])
    await state.set_state(AdminFlows.add_category_name)
    await state.update_data(edit_cat=cid)
    await cb.message.answer("New title:")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:cat:del:"))
async def cat_del(cb: CallbackQuery, session):
    cid = int(cb.data.split(":")[-1])
    c = await session.get(Category, cid)
    # reassign products
    if c:
        prods = (await session.execute(select(Product).where(Product.category_id == cid))).scalars().all()
        for p in prods:
            p.category_id = None
        await session.delete(c)
        await session.commit()
        await cb.message.answer(f"🗑️ Deleted {c.title}")
    await cb.answer()


# ---------------------------------------------------------------- gift codes & payments
@router.callback_query(F.data == "adm:payments")
async def payments_menu(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 New gift code", callback_data="adm:gift:new"), InlineKeyboardButton(text="🎁 List codes", callback_data="adm:gift:list")],
        [InlineKeyboardButton(text="🏦 Gateway settings", callback_data="adm:gw:list"), InlineKeyboardButton(text="🧾 Pending receipts", callback_data="adm:receipts")],
        [InlineKeyboardButton(text="📉 Sale discounts", callback_data="adm:sale:list")],
    ])
    await cb.message.answer("💳 Payments:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:gift:new")
async def gift_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.gift_amount)
    await cb.message.answer("Gift amount (toman):")
    await cb.answer()


@router.message(AdminFlows.gift_amount, F.text.regexp(r"^\d+$"))
async def gift_amount(message: Message, state: FSMContext):
    await state.update_data(gift_amount=int(message.text))
    await state.set_state(AdminFlows.gift_limit)
    await message.answer("Usage limit (number, e.g. 1):")


@router.message(AdminFlows.gift_limit, F.text.regexp(r"^\d+$"))
async def gift_limit(message: Message, state: FSMContext, session):
    data = await state.get_data()
    amount = data["gift_amount"]
    limit = int(message.text)
    code = "GIFT" + secrets.token_hex(4).upper()
    session.add(Discount(code=code, amount=amount, usage_limit=limit))
    await session.commit()
    await state.clear()
    await message.answer(f"🎁 Code: `{code}` — {amount:,} × {limit} use(s)", parse_mode="Markdown")


@router.callback_query(F.data == "adm:gift:list")
async def gift_list(cb: CallbackQuery, session):
    rows = (await session.execute(select(Discount))).scalars().all()
    lines = [f"• {r.code}: {r.amount:,} ×{r.usage_limit} used {r.used_count}" + (f" exp {r.expires_at:%Y-%m-%d}" if r.expires_at else "") for r in rows]
    await cb.message.answer("🎁 Gift codes:\n" + ("\n".join(lines) or "(none)"))
    await cb.answer()


@router.callback_query(F.data == "adm:sale:list")
async def sale_list(cb: CallbackQuery, session):
    rows = (await session.execute(select(SaleDiscount).order_by(SaleDiscount.min_referrals))).scalars().all()
    lines = [f"• ≥{r.min_referrals} refs → {r.percent_off}% off" for r in rows]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Add tier", callback_data="adm:sale:add")]])
    await cb.message.answer("📉 Sale discounts:\n" + ("\n".join(lines) or "(none)"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:sale:add")
async def sale_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.discount_min_refs)
    await cb.message.answer("Min referrals for this tier:")
    await cb.answer()


@router.message(AdminFlows.discount_min_refs, F.text.regexp(r"^\d+$"))
async def sale_min_refs(message: Message, state: FSMContext):
    await state.update_data(sale_min=int(message.text))
    await state.set_state(AdminFlows.discount_percent)
    await message.answer("Percent off (1-100):")


@router.message(AdminFlows.discount_percent, F.text.regexp(r"^\d{1,3}$"))
async def sale_percent(message: Message, state: FSMContext, session):
    pct = int(message.text)
    if not 1 <= pct <= 100:
        await message.answer("1-100 please:")
        return
    data = await state.get_data()
    session.add(SaleDiscount(min_referrals=data["sale_min"], percent_off=pct))
    await session.commit()
    await state.clear()
    await message.answer("✅ Tier added.")


@router.callback_query(F.data == "adm:gw:list")
async def gw_list(cb: CallbackQuery, session):
    rows = (await session.execute(select(GatewaySetting))).scalars().all()
    lines = [f"• {r.gateway}.{r.key} = {(r.value or '')[:40]}" for r in rows]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Set gateway key", callback_data="adm:gw:set")]])
    await cb.message.answer("🏦 Gateway settings:\n" + ("\n".join(lines) or "(none)"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:gw:set")
async def gw_set(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.setting_key)
    await state.update_data(gw_mode=True)
    await cb.message.answer("Send as `gateway.key` e.g. `card.card_number`:")
    await cb.answer()


# ---------------------------------------------------------------- receipts
@router.callback_query(F.data == "adm:receipts")
async def pending_receipts(cb: CallbackQuery, session):
    from mirza.db.models import PaymentReport

    pend = ((await session.execute(select(PaymentReport).where(PaymentReport.gateway == "card", PaymentReport.payment_status == "pending"))).scalars().all())
    if not pend:
        return await cb.answer("(none)", show_alert=True)
    for r in pend:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Approve", callback_data=f"rcpt:ok:{r.order_id}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"rcpt:no:{r.order_id}")]])
        meta = r.meta or {}
        fid = meta.get("receipt_file_id")
        caption = f"🧾 {r.order_id}\nUser {r.user_id}: {r.price:,}"
        if fid:
            try:
                await cb.message.bot.send_photo(cb.from_user.id, fid, caption=caption, reply_markup=kb)
                continue
            except Exception:
                pass
        await cb.message.answer(caption, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("rcpt:ok:"))
async def receipt_approve(cb: CallbackQuery, session):
    from mirza.services.wallet import WalletService
    order = cb.data.split(":", 2)[2]
    rep = await WalletService(session).mark_paid(order)
    if rep and rep.payment_status == "paid":
        await cb.message.edit_text((cb.message.text or cb.message.caption or "") + "\n\n✅ approved")
        try:
            await cb.bot.send_message(rep.user_id, f"✅ Your payment {order} approved. Balance credited.")
        except Exception:
            pass
    await cb.answer()


@router.callback_query(F.data.startswith("rcpt:no:"))
async def receipt_reject(cb: CallbackQuery, session):
    from mirza.db.models import PaymentReport
    order = cb.data.split(":", 2)[2]
    rep = (await session.execute(select(PaymentReport).where(PaymentReport.order_id == order))).scalar_one_or_none()
    if rep and rep.payment_status != "paid":
        rep.payment_status = "canceled"
        await session.commit()
        try:
            await cb.message.edit_text((cb.message.text or cb.message.caption or "") + "\n\n❌ rejected")
        except Exception:
            await cb.message.answer("❌ rejected")
        try:
            await cb.bot.send_message(rep.user_id, f"❌ Your payment {order} was rejected. Contact support.")
        except Exception:
            pass
    await cb.answer()


# ---------------------------------------------------------------- settings KV + texts
@router.callback_query(F.data == "adm:settings")
async def settings_menu(cb: CallbackQuery, session):
    rows = (await session.execute(select(BotSetting))).scalars().all()
    lines = [f"`{r.key}` = `{r.value[:60]}`" for r in rows[:30]]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Set key", callback_data="adm:kv:set")],
        [InlineKeyboardButton(text="🔙", callback_data="adm:settings")],
    ])
    await cb.message.answer("⚙️ Settings KV:\n" + ("\n".join(lines) or "(empty)"), parse_mode="Markdown", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:kv:set")
async def kv_set_key(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.setting_key)
    await state.update_data(gw_mode=False)
    await cb.message.answer("Send key (e.g. `Extra_volume`, `price_per_day`, `channel_lock`, `require_rules`):", parse_mode="Markdown")
    await cb.answer()


@router.message(AdminFlows.setting_key)
async def kv_key(message: Message, state: FSMContext):
    key = message.text.strip()
    if not key or " " in key:
        await message.answer("Invalid key, no spaces please:")
        return
    await state.update_data(setting_key=key)
    await state.set_state(AdminFlows.setting_value)
    await message.answer(f"Send value for `{key}`:", parse_mode="Markdown")


@router.message(AdminFlows.setting_value)
async def kv_value(message: Message, state: FSMContext, session):
    data = await state.get_data()
    gw_mode = data.get("gw_mode")
    if gw_mode:
        # gateway.key
        raw = data.get("setting_key", "")
        if "." in raw:
            gw, key = raw.split(".", 1)
            row = (await session.execute(select(GatewaySetting).where(GatewaySetting.gateway == gw, GatewaySetting.key == key))).scalar_one_or_none()
            if row:
                row.value = message.text.strip()
            else:
                session.add(GatewaySetting(gateway=gw, key=key, value=message.text.strip()))
            await session.commit()
            await state.clear()
            await message.answer(f"✅ Gateway {gw}.{key} set.")
            return
        # fallthrough to normal key
    key = data.get("setting_key")
    val = message.text.strip()
    if not key:
        await state.clear()
        await message.answer("Session expired. Try again.")
        return
    row = (await session.execute(select(BotSetting).where(BotSetting.key == key))).scalar_one_or_none()
    if row:
        row.value = val
    else:
        session.add(BotSetting(key=key, value=val))
    await session.commit()
    await state.clear()
    await message.answer(f"✅ `{key}` = `{val[:80]}`", parse_mode="Markdown")


@router.callback_query(F.data == "adm:texts")
async def texts_menu(cb: CallbackQuery, session):
    rows = (await session.execute(select(TextOverride))).scalars().all()
    lines = [f"• {r.key}: {(r.text or '')[:60]}" for r in rows[:20]]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Edit text", callback_data="adm:text:edit")], [InlineKeyboardButton(text="📚 Help entries", callback_data="adm:help:list")]])
    await cb.message.answer("📚 Texts:\n" + ("\n".join(lines) or "(none)"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:text:edit")
async def text_edit_key(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.edit_text_key)
    await cb.message.answer("Send text key (e.g. `support`, `rules`, `help`):")
    await cb.answer()


@router.message(AdminFlows.edit_text_key)
async def text_key(message: Message, state: FSMContext):
    await state.update_data(text_key=message.text.strip())
    await state.set_state(AdminFlows.edit_text_value)
    await message.answer("Send new text (HTML allowed):")


@router.message(AdminFlows.edit_text_value)
async def text_value(message: Message, state: FSMContext, session):
    data = await state.get_data()
    key = data["text_key"]
    row = (await session.execute(select(TextOverride).where(TextOverride.key == key))).scalar_one_or_none()
    if row:
        row.text = message.text or message.html_text or ""
    else:
        session.add(TextOverride(key=key, text=message.text or message.html_text or ""))
    await session.commit()
    await state.clear()
    await message.answer(f"✅ Text `{key}` updated.", parse_mode="Markdown")


@router.callback_query(F.data == "adm:help:list")
async def help_list(cb: CallbackQuery, session):
    rows = (await session.execute(select(HelpEntry))).scalars().all()
    lines = [f"• {r.id}: {r.title}" for r in rows]
    await cb.message.answer("📚 Help entries:\n" + ("\n".join(lines) or "(none)"))
    await cb.answer()


# ---------------------------------------------------------------- admins
@router.callback_query(F.data == "adm:admins")
async def admins_menu(cb: CallbackQuery, session):
    rows = (await session.execute(select(Admin))).scalars().all()
    lines = [f"• {r.id}" for r in rows]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add admin", callback_data="adm:admin:add")],
        [InlineKeyboardButton(text="➖ Remove admin", callback_data="adm:admin:del")],
    ])
    await cb.message.answer("👑 Admins:\n" + ("\n".join(lines) or "(none)"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "adm:admin:add")
async def admin_add_prompt(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.add_admin)
    await cb.message.answer("Send admin telegram user id:")
    await cb.answer()


@router.message(AdminFlows.add_admin, F.text.regexp(r"^\d{3,15}$"))
async def add_admin_id(message: Message, state: FSMContext, session):
    uid = int(message.text.strip())
    exists = await session.get(Admin, uid)
    if not exists:
        session.add(Admin(id=uid))
        await session.commit()
    await state.clear()
    await message.answer(f"✅ admin {uid} added")


@router.callback_query(F.data == "adm:admin:del")
async def admin_del_prompt(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminFlows.remove_admin)
    await cb.message.answer("Send admin id to remove:")
    await cb.answer()


@router.message(AdminFlows.remove_admin, F.text.regexp(r"^\d{3,15}$"))
async def remove_admin_id(message: Message, state: FSMContext, session):
    uid = int(message.text.strip())
    row = await session.get(Admin, uid)
    if row:
        await session.delete(row)
        await session.commit()
        await message.answer(f"🗑️ admin {uid} removed")
    else:
        await message.answer("Not an admin")
    await state.clear()
