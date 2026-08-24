"""User-side handlers: start, main menu, buy flow, wallet, referral, gift, services."""
from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy import select

from mirza.bot.middleware import is_valid_phone
from mirza.core.registry import registry
from mirza.db.models import BotSetting, Category, Invoice, Product, User
from mirza.i18n.translate import t
from mirza.services.purchase import PurchaseError, PurchaseService
from mirza.services.referral import ReferralService
from mirza.services.wallet import WalletService

from ..fsm.states import BuyFlow, GiftCodeFlow, PhoneFlow, TopUpFlow

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


def phone_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("users.phone.ask"), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _maybe_require_phone(message: Message, user: User, session) -> bool:
    """Return True if we intercepted and asked for phone."""
    # settings: get_number == "1" means require phone
    v = (await session.execute(select(BotSetting.value).where(BotSetting.key == "get_number"))).scalar_one_or_none()
    if v != "1":
        return False
    if user.phone_number and user.phone_number not in (None, "", "none"):
        return False
    await message.answer(t("users.phone.ask"), reply_markup=phone_request_kb())
    return True


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session, user, command: CommandObject | None = None):
    await state.clear()
    # rules gate: offer accept button if not yet accepted
    if not user.rules_accepted:
        v = (await session.execute(select(BotSetting.value).where(BotSetting.key == "require_rules"))).scalar_one_or_none()
        if v == "1":
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Accept rules", callback_data="accept_rules")]])
            await message.answer("♨️ Please accept rules first.", reply_markup=kb)
            return
    # deep-link referral binding (?start=<refcode>)
    if command and command.args and len(command.args) == 32:
        ref = ReferralService(session)
        referrer = await ref.resolve(command.args)
        if referrer:
            ok = await ref.bind(user.id, referrer)
            if ok:
                await message.answer("✅ Referral linked.")
    # phone gate
    if await _maybe_require_phone(message, user, session):
        return
    await message.answer(
        t("users.start", name=message.from_user.first_name or "", shop="Mirza"),
        reply_markup=main_menu_kb(),
    )


# ---------------------------------------------------------------- phone handlers
@router.message(PhoneFlow.share_number, F.contact)
@router.message(F.contact)
async def phone_receive(message: Message, session, user):
    contact = message.contact
    if contact.user_id != user.id:
        await message.answer("Please share *your own* contact.", parse_mode="Markdown")
        return
    digits = contact.phone_number.lstrip("+")
    # iran_only check
    iran_only = ((await session.execute(select(BotSetting.value).where(BotSetting.key == "iran_number"))).scalar_one_or_none() or "0") == "1"
    if iran_only and not digits.startswith("98"):
        await message.answer(t("users.phone.iran_only"))
        return
    if not is_valid_phone(digits, iran_only=iran_only):
        await message.answer(t("users.phone.invalid"))
        return
    user.phone_number = digits
    await session.commit()
    await message.answer("✅ Phone saved.", reply_markup=main_menu_kb())
    await message.answer(t("users.start", name=message.from_user.first_name or "", shop="Mirza"), reply_markup=main_menu_kb())


@router.message(PhoneFlow.share_number, F.text)
async def phone_text_fallback(message: Message, session, user):
    iran_only = ((await session.execute(select(BotSetting.value).where(BotSetting.key == "iran_number"))).scalar_one_or_none() or "0") == "1"
    if not is_valid_phone(message.text or "", iran_only=iran_only):
        await message.answer(t("users.phone.invalid"), reply_markup=phone_request_kb())
        return
    digits = message.text.strip().lstrip("+")
    user.phone_number = digits
    await session.commit()
    await message.answer("✅ Phone saved.", reply_markup=main_menu_kb())


# ---------------------------------------------------------------- buy flow
@router.callback_query(F.data == "buy")
async def buy_start(cb: CallbackQuery, session, user):
    # phone gate
    v = (await session.execute(select(BotSetting.value).where(BotSetting.key == "get_number"))).scalar_one_or_none()
    if v == "1" and (not user.phone_number or user.phone_number in ("none", "")):
        await cb.message.answer(t("users.phone.ask"), reply_markup=phone_request_kb())
        await cb.answer()
        return
    cats = (await session.execute(select(Category))).scalars().all()
    if not cats:
        # no categories → show all products directly (legacy statuscategory=0 path)
        prods = (await session.execute(select(Product))).scalars().all()
        if not prods:
            await cb.message.answer("No products available yet.")
            await cb.answer()
            return
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"{p.name} — {p.price:,}", callback_data=f"prod:{p.id}")] for p in prods
            ] + [[InlineKeyboardButton(text="🛒 Custom order", callback_data="buy_custom")]]
        )
        await cb.message.answer(t("users.buy.choose_product"), reply_markup=kb)
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c.title, callback_data=f"cat:{c.id}")] for c in cats
        ] + [[InlineKeyboardButton(text="🛒 Custom order", callback_data="buy_custom")],
             [InlineKeyboardButton(text=t("users.menu.back"), callback_data="menu")]]
    )
    await cb.message.answer(t("users.buy.choose_category"), reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("cat:"))
async def list_products(cb: CallbackQuery, session):
    cid = int(cb.data.split(":")[1])
    prods = (await session.execute(select(Product).where(Product.category_id == cid))).scalars().all()
    if not prods:
        await cb.message.answer("No products in this category.")
        await cb.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{p.name} — {p.price:,}", callback_data=f"prod:{p.id}")] for p in prods
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
    # apply referral tier discount if any
    from mirza.db.models import SaleDiscount
    from sqlalchemy import select as _sel

    ref_cnt = user.referral_count or 0
    disc = (await session.execute(_sel(SaleDiscount).where(SaleDiscount.min_referrals <= ref_cnt).order_by(SaleDiscount.min_referrals.desc()))).scalars().first()
    price = p.price
    if disc and disc.percent_off:
        price = int(price * (100 - disc.percent_off) / 100)
    text = t("users.buy.invoice", product=p.name, location=p.location or "-", volume=f"{p.volume_gb} GB", duration=f"{p.duration_days}d", price=f"{price:,}")
    if disc and disc.percent_off:
        text += f"\n🎁 {disc.percent_off}% referral discount applied!"
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
    if not p:
        return await cb.answer("not found", show_alert=True)
    # recompute discounted price
    from mirza.db.models import SaleDiscount
    disc = (await session.execute(select(SaleDiscount).where(SaleDiscount.min_referrals <= (user.referral_count or 0)).order_by(SaleDiscount.min_referrals.desc()))).scalars().first()
    price = p.price
    if disc and disc.percent_off:
        price = int(price * (100 - disc.percent_off) / 100)
    wallet = WalletService(session)
    if not await wallet.charge(user.id, price, reason=f"buy:{p.name}"):
        return await cb.message.answer(t("users.balance.insufficient"))
    try:
        result = await PurchaseService(session).provision(user.id, product=p)
    except PurchaseError as e:
        await wallet.add_balance(user.id, price, reason="refund:provision_failed", actor_id=user.id)
        log.error("purchase.failed", user=user.id, err=str(e))
        return await cb.message.answer(t("users.buy.failed", reason=str(e)))
    sub = result.panel_user.subscription_url
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Subscription", url=sub)]]) if sub and sub.startswith("http") else None
    # also send links as monospace if any
    extra = ""
    if result.panel_user.links:
        extra = "\n\n" + "\n".join(result.panel_user.links[:3])
    await cb.message.answer(t("users.buy.success", sub_url=sub or "(see links)") + extra, reply_markup=kb)


# ---- custom order flow
@router.callback_query(F.data == "buy_custom")
async def buy_custom_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BuyFlow.custom_volume)
    await cb.message.answer("📊 Enter desired volume in GB (e.g. 50):")
    await cb.answer()


@router.message(BuyFlow.custom_volume, F.text.regexp(r"^\d{1,4}$"))
async def buy_custom_volume(message: Message, state: FSMContext):
    await state.update_data(custom_volume=int(message.text))
    await state.set_state(BuyFlow.custom_duration)
    await message.answer("⏳ Enter duration in days (e.g. 30):")


@router.message(BuyFlow.custom_duration, F.text.regexp(r"^\d{1,4}$"))
async def buy_custom_duration(message: Message, state: FSMContext, session):
    await state.update_data(custom_duration=int(message.text))
    data = await state.get_data()
    vol = data["custom_volume"]
    days = int(message.text)
    # price: per-GB + per-day from settings
    per_gb = int((await session.execute(select(BotSetting.value).where(BotSetting.key == "Extra_volume"))).scalar_one_or_none() or 0) or 1000
    per_day = int((await session.execute(select(BotSetting.value).where(BotSetting.key == "price_per_day"))).scalar_one_or_none() or 0) or 500
    price = vol * per_gb + days * per_day
    await state.update_data(custom_price=price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Pay {price:,} from wallet", callback_data="pay_custom")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="menu")],
    ])
    await message.answer(t("users.buy.invoice", product="Custom", location="auto", volume=f"{vol} GB", duration=f"{days}d", price=f"{price:,}"), reply_markup=kb)


@router.callback_query(F.data == "pay_custom")
async def pay_custom(cb: CallbackQuery, state: FSMContext, session, user):
    data = await state.get_data()
    vol = data.get("custom_volume")
    days = data.get("custom_duration")
    price = data.get("custom_price")
    if not vol or not days:
        await cb.answer("Expired, start again", show_alert=True)
        await state.clear()
        return
    # pick first enabled panel as location (admin can set Location on products but custom uses auto)
    from mirza.db.models import PanelServer
    panel = (await session.execute(select(PanelServer).where(PanelServer.enabled.is_(True)))).scalars().first()
    if not panel:
        await cb.message.answer("No panels available.")
        await state.clear()
        await cb.answer()
        return
    wallet = WalletService(session)
    if not await wallet.charge(user.id, price, reason="buy:custom"):
        await cb.message.answer(t("users.balance.insufficient"))
        await cb.answer()
        return
    try:
        result = await PurchaseService(session).provision(user.id, custom={"location": panel.name, "volume_gb": vol, "duration_days": days, "price": price, "name": f"custom-{vol}GB-{days}d"})
    except PurchaseError as e:
        await wallet.add_balance(user.id, price, reason="refund:custom_failed", actor_id=user.id)
        await cb.message.answer(t("users.buy.failed", reason=str(e)))
        await state.clear()
        await cb.answer()
        return
    await state.clear()
    sub = result.panel_user.subscription_url
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Subscription", url=sub)]]) if sub and sub.startswith("http") else None
    await cb.message.answer(t("users.buy.success", sub_url=sub or "-"), reply_markup=kb)
    await cb.answer()


# ---------------------------------------------------------------- services
@router.callback_query(F.data == "services")
async def my_services(cb: CallbackQuery, session, user):
    invs = ((await session.execute(select(Invoice).where(Invoice.user_id == user.id, Invoice.status != "deleted"))).scalars().all())
    if not invs:
        await cb.message.answer("No services yet. Use 🛒 Buy to get started.", reply_markup=main_menu_kb())
        await cb.answer()
        return
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("users.menu.topup"), callback_data="topup")]])
    await cb.message.answer("Choose:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "topup")
async def topup_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(TopUpFlow.amount)
    await cb.message.answer("💰 Enter amount (toman, e.g. 100000):")
    await cb.answer()


@router.message(TopUpFlow.amount, F.text.regexp(r"^\d{4,12}$"))
async def topup_amount(message: Message, state: FSMContext, session, user):
    amount = int(message.text)
    if amount < 10000:
        await message.answer("Minimum 10,000.")
        return
    await state.update_data(amount=amount)
    await state.set_state(TopUpFlow.gateway)
    gws = registry.list("payment")
    rows = [[InlineKeyboardButton(text=f"{n} ({r})", callback_data=f"gw:{n}:{r}")] for _, n, r in gws]
    rows.append([InlineKeyboardButton(text="❌ Cancel", callback_data="menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer("Choose payment gateway:", reply_markup=kb)


@router.callback_query(F.data.startswith("gw:"))
async def topup_gateway(cb: CallbackQuery, state: FSMContext, session, user, settings):
    _, name, rev = cb.data.split(":", 2)
    data = await state.get_data()
    amount = data.get("amount")
    if not amount:
        await cb.answer("Expired", show_alert=True)
        await state.clear()
        return
    # card-to-card → ask for receipt photo
    if name == "card":
        from mirza.db.models import PaymentReport

        # create pending report and ask for receipt
        from mirza.payments.base import new_order_id
        order = new_order_id()
        session.add(PaymentReport(order_id=order, user_id=user.id, price=amount, gateway="card", payment_status="pending"))
        await session.commit()
        await state.update_data(order_id=order)
        await state.set_state(TopUpFlow.card_receipt)
        # fetch card info from gateway_settings
        from sqlalchemy import select as _sel
        from mirza.db.models import GatewaySetting
        card_no = (await session.execute(_sel(GatewaySetting.value).where(GatewaySetting.gateway == "card", GatewaySetting.key == "card_number"))).scalar_one_or_none() or "—"
        card_holder = (await session.execute(_sel(GatewaySetting.value).where(GatewaySetting.gateway == "card", GatewaySetting.key == "card_holder"))).scalar_one_or_none() or ""
        await cb.message.answer(f"💳 Card-to-card:\nCard: `{card_no}`\nHolder: {card_holder}\nAmount: {amount:,}\n\nSend a photo of the receipt after transfer.", parse_mode="Markdown")
        await cb.answer()
        return
    # gateway with external pay URL
    cls = registry.get("payment", name, rev)
    if not cls:
        await cb.message.answer("Gateway not configured.")
        await state.clear()
        await cb.answer()
        return
    # load gateway config from DB
    from mirza.db.models import GatewaySetting
    cfg_rows = (await session.execute(select(GatewaySetting).where(GatewaySetting.gateway == name))).scalars().all()
    cfg = {r.key: r.value for r in cfg_rows}
    # fallback to env
    if not cfg:
        cfg = {"api_key": settings.web.webhook_secret}  # placeholder to trigger error visibly
    try:
        from mirza.payments.base import new_order_id, PaymentRequest

        order = new_order_id()
        gw = cls(config=cfg)
        res = await gw.create_payment(PaymentRequest(order_id=order, user_id=user.id, amount=amount, description=f"Topup {amount}"))
        # persist report
        from mirza.db.models import PaymentReport
        session.add(PaymentReport(order_id=order, user_id=user.id, price=amount, gateway=name, payment_status="pending", meta={"gateway_ref": res.gateway_ref}))
        await session.commit()
        if res.ok and res.pay_url:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Pay now", url=res.pay_url)]])
            await cb.message.answer(f"Order {order}: {amount:,} — click to pay:", reply_markup=kb)
        else:
            await cb.message.answer(f"Gateway error: {res.message or 'unknown'}")
    except Exception as e:
        log.error("topup.gateway_error", gateway=name, err=str(e))
        await cb.message.answer(t("common.error"))
    await state.clear()
    await cb.answer()


@router.message(TopUpFlow.card_receipt, F.photo)
async def card_receipt_photo(message: Message, state: FSMContext, session, user, settings):
    data = await state.get_data()
    order = data.get("order_id")
    if not order:
        await state.clear()
        return
    file_id = message.photo[-1].file_id
    # store file_id in report meta
    from sqlalchemy import select as _sel
    from mirza.db.models import PaymentReport
    rep = (await session.execute(_sel(PaymentReport).where(PaymentReport.order_id == order))).scalar_one_or_none()
    if rep:
        rep.meta = {"receipt_file_id": file_id, **(rep.meta or {})}
        await session.commit()
    # notify admins
    for admin_id in (settings.telegram.admin_ids or []):
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Approve", callback_data=f"rcpt:ok:{order}"),
                 InlineKeyboardButton(text="❌ Reject", callback_data=f"rcpt:no:{order}")]])
            await message.bot.send_photo(admin_id, file_id, caption=f"🧾 Card receipt\nOrder: {order}\nUser: {user.id}\nAmount: {rep.price if rep else '?'}", reply_markup=kb)
        except Exception:
            pass
    await state.clear()
    await message.answer("✅ Receipt sent for review. You'll be notified.", reply_markup=main_menu_kb())


# ---------------------------------------------------------------- referral/gift/support
@router.callback_query(F.data == "referral")
async def referral_menu(cb: CallbackQuery, session, user, settings):
    svc = ReferralService(session)
    stats = await svc.stats_for(user.id)
    bot_name = (await session.execute(select(BotSetting.value).where(BotSetting.key == "bot_username"))).scalar_one_or_none() or "bot"
    link = f"https://t.me/{bot_name}?start={user.ref_code}"
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


@router.callback_query(F.data == "support")
async def support_menu(cb: CallbackQuery, session):
    # admin-editable text overrides
    from mirza.db.models import TextOverride
    ov = (await session.execute(select(TextOverride.text).where(TextOverride.key == "support"))).scalar_one_or_none()
    text = ov or t("users.menu.support") + " — contact admin."
    # also try HelpEntry fallback
    if not ov:
        from mirza.db.models import HelpEntry
        h = (await session.execute(select(HelpEntry.body).where(HelpEntry.title == "support"))).scalar_one_or_none()
        if h:
            text = h
    await cb.message.answer(text)
    await cb.answer()


@router.callback_query(F.data == "menu")
async def back_to_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("🏠", reply_markup=main_menu_kb())
    await cb.answer()
