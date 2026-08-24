"""Unit tests for wallet service with in-memory SQLite."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mirza.db.models import Base, Discount, PaymentReport, User
from mirza.services.wallet import WalletService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest_asyncio.fixture
async def user(db):
    async with db() as s:
        u = User(id=1000, ref_code="a" * 32, balance=50_000)
        s.add(u)
        await s.commit()
        return 1000


async def test_charge_and_refund(db, user):
    async with db() as s:
        w = WalletService(s)
        assert await w.charge(user, 30_000, reason="buy") is True
        assert await w.charge(user, 30_000, reason="over") is False  # insufficient
        await w.add_balance(user, 5_000, reason="refund")
        u = await s.get(User, user)
        assert u.balance == 25_000


async def test_gift_code_lifecycle(db, user):
    async with db() as s:
        s.add(Discount(code="NOWRUZ", amount=10_000, usage_limit=1))
        await s.commit()
        w = WalletService(s)
        ok, _ = await w.redeem_gift_code(user, "NOWRUZ")
        assert ok
        # second redeem by same user -> duplicate rejected
        ok2, why = await w.redeem_gift_code(user, "NOWRUZ")
        assert not ok2 and why == "already_used"
        # different user -> exhausted (limit reached)
        s.add(User(id=2000, ref_code="b" * 32))
        await s.commit()
        ok3, why3 = await w.redeem_gift_code(2000, "NOWRUZ")
        assert not ok3 and why3 == "exhausted"


async def test_mark_paid_idempotent(db, user):
    async with db() as s:
        w = WalletService(s)
        rep = await w.create_topup(user, 7_000, "nowpayments")
        order = rep.order_id
        await w.mark_paid(order)
        await w.mark_paid(order)  # double webhook
        r = (await s.get(PaymentReport, rep.id))
        assert r.payment_status == "paid"
        u = await s.get(User, user)
        assert u.balance == 57_000  # credited exactly once
