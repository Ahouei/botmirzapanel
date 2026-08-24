"""Clean-schema SQLAlchemy 2.0 models. Mirrors every legacy botmirzapanel entity,
renamed and normalized. Legacy names noted in docstrings for the importer."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def json_col() -> Mapped[Any]:
    """JSONB on PostgreSQL, portable JSON elsewhere (SQLite dev)."""
    return mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True, default=None)


# ---------------------------------------------------------------- users
class User(Base):
    """legacy table ``user``"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram id
    ref_code: Mapped[str] = mapped_column(String(32), unique=True)
    step: Mapped[str] = mapped_column(String(64), default="none")
    status: Mapped[str] = mapped_column(String(32), default="Active")  # legacy User_Status
    balance: Mapped[int] = mapped_column(default=0)  # legacy Balance
    phone_number: Mapped[str | None] = mapped_column(String(32), default=None)  # legacy number
    username: Mapped[str | None] = mapped_column(String(255), default="none")
    page_number: Mapped[int] = mapped_column(default=1)
    message_count: Mapped[int] = mapped_column(default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    test_limit: Mapped[int] = mapped_column(default=0)  # legacy limit_usertest
    referral_count: Mapped[int] = mapped_column(default=0)  # legacy affiliatescount
    referred_by: Mapped[int | None] = mapped_column(BigInteger, default=None)  # legacy affiliates
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # legacy verify
    blocked_reason: Mapped[str | None] = mapped_column(Text, default=None)  # legacy description_blocking
    rules_accepted: Mapped[bool] = mapped_column(Boolean, default=False)  # legacy roll_Status

    # in-flight purchase scratchpad (legacy Processing_value / _one / _tow / _four)
    pending: Mapped[Any] = json_col()


class Admin(Base):
    """legacy table ``admin``"""
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram id


class ChannelLock(Base):
    """legacy table ``channels`` - forced join channel"""
    __tablename__ = "channel_locks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link: Mapped[str] = mapped_column(String(600))


# ---------------------------------------------------------------- catalog
class Category(Base):
    """legacy table ``category``"""
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))


class Product(Base):
    """legacy table ``product``"""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(String(64), unique=True)  # legacy code_product
    name: Mapped[str] = mapped_column(String(255))  # legacy name_product
    price: Mapped[int] = mapped_column(default=0)  # legacy price_product
    volume_gb: Mapped[int] = mapped_column(default=0)  # legacy Volume_constraint
    location: Mapped[str | None] = mapped_column(String(255), default=None)  # panel name
    duration_days: Mapped[int] = mapped_column(default=30)  # legacy Service_time
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), default=None)


class PanelServer(Base):
    """legacy table ``marzban_panel`` - any VPN backend instance"""
    __tablename__ = "panel_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)  # legacy name_panel
    url: Mapped[str] = mapped_column(String(600))
    username: Mapped[str | None] = mapped_column(String(255), default=None)
    password: Mapped[str | None] = mapped_column(String(255), default=None)
    plugin: Mapped[str] = mapped_column(String(64))  # marzban|x-ui|alireza|s_ui|wgdashboard|mikrotik|marzneshin
    revision: Mapped[str] = mapped_column(String(64), default="default")
    enabled: Mapped[bool] = mapped_column(default=True)  # legacy status == activepanel
    allow_test: Mapped[bool] = mapped_column(default=False)  # legacy statusTest
    sub_url_base: Mapped[str | None] = mapped_column(String(600), default=None)  # legacy linksubx/sublink
    inbound_id: Mapped[str | None] = mapped_column(String(255), default=None)
    username_method: Mapped[str] = mapped_column(String(64), default="random")  # legacy MethodUsername
    manual_config: Mapped[bool] = mapped_column(default=False)  # legacy configManual
    on_hold: Mapped[bool] = mapped_column(default=False)  # legacy onholdstatus
    token_cache: Mapped[Any] = json_col()  # legacy datelogin
    extra: Mapped[Any] = json_col()  # legacy inbounds/proxies


# ---------------------------------------------------------------- sales
class Invoice(Base):
    """legacy table ``invoice``"""
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    product_name: Mapped[str | None] = mapped_column(String(255))  # legacy name_product
    panel_name: Mapped[str | None] = mapped_column(String(255))  # legacy Service_location
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # legacy time_sell
    price: Mapped[int] = mapped_column(default=0)
    volume_gb: Mapped[int] = mapped_column(default=0)  # legacy Volume
    duration_days: Mapped[int] = mapped_column(default=0)  # legacy Service_time
    service_username: Mapped[str | None] = mapped_column(String(255))  # panel-side username
    config_payload: Mapped[Any] = json_col()  # legacy user_info (links/suburl/qr)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # active|end_of_time|end_of_volume|expired|deleted...


class PaymentReport(Base):
    """legacy table ``Payment_report``"""
    __tablename__ = "payment_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int]
    price: Mapped[int] = mapped_column(default=0)
    gateway: Mapped[str] = mapped_column(String(32))  # nowpayments|aqayepardakht|cardtocart|wallet
    payment_status: Mapped[str] = mapped_column(String(32), default="pending")  # paid|pending|canceled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    meta: Mapped[Any] = json_col()


# ---------------------------------------------------------------- promos
class Discount(Base):
    """legacy table ``Discount`` - gift codes for wallet top-up"""
    __tablename__ = "discounts"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    amount: Mapped[int] = mapped_column(default=0)
    usage_limit: Mapped[int] = mapped_column(default=1)
    used_count: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class GiftCodeRedemption(Base):
    """legacy table ``Giftcodeconsumed``"""
    __tablename__ = "gift_code_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SaleDiscount(Base):
    """legacy table ``DiscountSell`` - % off per referral count tier"""
    __tablename__ = "sale_discounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    min_referrals: Mapped[int] = mapped_column(default=0)
    percent_off: Mapped[int] = mapped_column(default=0)


class Referral(Base):
    """legacy table ``affiliates``"""
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    referred_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    rewarded: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- misc/config
class BotSetting(Base):
    """legacy table ``setting`` - single row key/value-ish store"""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, default=None)


class TextOverride(Base):
    """legacy table ``textbot`` - admin-editable bot texts"""
    __tablename__ = "text_overrides"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    text: Mapped[str] = mapped_column(Text, default="")


class GatewaySetting(Base):
    """legacy tables ``PaySetting`` + parts of setting"""
    __tablename__ = "gateway_settings"

    gateway: Mapped[str] = mapped_column(String(32), primary_key=True)  # nowpayments|aqayepardakht|card
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, default=None)


class HelpEntry(Base):
    """legacy table ``help``"""
    __tablename__ = "help_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")


class CancelRequest(Base):
    """legacy table ``cancel_service``"""
    __tablename__ = "cancel_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[str]
    user_id: Mapped[int]
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- new (improvements, no legacy equivalent) ---------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(128))
    target: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[Any] = json_col()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
