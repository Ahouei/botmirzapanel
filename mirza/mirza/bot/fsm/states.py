"""FSM states - replaces the PHP `step` column state machine."""
from aiogram.fsm.state import State, StatesGroup


class BuyFlow(StatesGroup):
    category = State()
    product = State()
    location = State()
    confirm = State()
    custom_volume = State()
    custom_duration = State()
    custom_confirm = State()


class TopUpFlow(StatesGroup):
    amount = State()
    gateway = State()
    card_receipt = State()  # photo/file_id for card-to-card


class GiftCodeFlow(StatesGroup):
    code = State()


class AdminFlows(StatesGroup):
    add_panel_url = State()
    add_panel_creds = State()
    edit_panel_field = State()
    add_product_name = State()
    add_product_price = State()
    add_product_volume = State()
    add_product_duration = State()
    add_product_location = State()
    add_category_name = State()
    edit_text_key = State()
    edit_text_value = State()
    broadcast_text = State()
    broadcast_confirm = State()
    find_user = State()
    block_user_reason = State()
    set_user_balance = State()
    send_message_text = State()
    send_message_target = State()
    add_admin = State()
    remove_admin = State()
    set_channel = State()
    gift_amount = State()
    gift_limit = State()
    discount_percent = State()
    discount_min_refs = State()
    setting_key = State()
    setting_value = State()
    inbound_select = State()


class PhoneFlow(StatesGroup):
    share_number = State()
