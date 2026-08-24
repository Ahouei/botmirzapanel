"""Tests for wallet top-up idempotency and card receipt flow."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mirza.db.models import Base, PaymentReport, User


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest.mark.asyncio
async def test_card_pending_and_approve(db):
    from mirza.services.wallet import WalletService
    from mirza.payments.base import new_order_id

    async with db() as s:
        s.add(User(id=10, ref_code="c" * 32, balance=0))
        await s.commit()
        order = new_order_id()
        s.add(PaymentReport(order_id=order, user_id=10, price=50000, gateway="card", payment_status="pending", meta={"receipt_file_id": "FILE123"}))
        await s.commit()
        rep = await WalletService(s).mark_paid(order)
        assert rep.payment_status == "paid"
        u = await s.get(User, 10)
        assert u.balance == 50000
        # idempotent second mark
        rep2 = await WalletService(s).mark_paid(order)
        assert rep2.payment_status == "paid"
        u2 = await s.get(User, 10)
        assert u2.balance == 50000  # not double credited


@pytest.mark.asyncio
async def test_referral_discount_applied(db):
    from mirza.db.models import SaleDiscount

    async with db() as s:
        s.add(User(id=20, ref_code="d" * 32, balance=100000, referral_count=5))
        s.add(SaleDiscount(min_referrals=3, percent_off=10))
        s.add(SaleDiscount(min_referrals=10, percent_off=20))
        await s.commit()
        u = await s.get(User, 20)
        # simulate checkout discount logic from handlers/user.py
        from sqlalchemy import select

        disc = (await s.execute(select(SaleDiscount).where(SaleDiscount.min_referrals <= u.referral_count).order_by(SaleDiscount.min_referrals.desc()))).scalars().first()
        assert disc.percent_off == 10
        price = 100000
        discounted = int(price * (100 - disc.percent_off) / 100)
        assert discounted == 90000
