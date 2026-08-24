"""FSM states - replaces the PHP `step` column state machine."""
from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    category = State()
    product = State()
    location = State()
    confirm = State()
    custom_volume = State()
    custom_duration = State()


class TopUpFlow(StatesGroup):
    amount = State()
    gateway = State()


class GiftCodeFlow(StatesGroup):
    code = State()


class AdminFlows(StatesGroup):
    add_panel_url = State()
    add_panel_creds = State()
    add_product_name = State()
    add_product_price = State()
    add_product_volume = State()
    add_product_days = State()
    broadcast_text = State()
    broadcast_confirm = State()
    find_user = State()
    block_user_reason = State()
    add_admin = State()
    set_channel = State()
    edit_text_key = State()
    reply_to_user = State()


class PhoneFlow(StatesGroup):
    share_number = State()
