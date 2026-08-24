"""Tests for middleware gates and broadcast queue."""
import json
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mirza.db.models import Base, BotSetting, User
from mirza.jobs.broadcast import enqueue, pop_queue, finish
from mirza.bot.middleware import is_valid_phone


def test_phone_validation():
    assert is_valid_phone("989123456789", iran_only=True)
    assert not is_valid_phone("49123456789", iran_only=True)
    assert is_valid_phone("+989123456789", iran_only=True)
    assert is_valid_phone("09123456789", iran_only=True)
    assert is_valid_phone("49123456789", iran_only=False)
    assert not is_valid_phone("abc", iran_only=False)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest.mark.asyncio
async def test_broadcast_enqueue_pop(db):
    async with db() as s:
        n = await enqueue(s, {"text": "hello"}, [1, 2, 3])
        assert n == 3
        job = await pop_queue(s)
        assert job["ids"] == [1, 2, 3]
        assert job["message"]["text"] == "hello"
        await finish(s)
        assert await pop_queue(s) is None


@pytest.mark.asyncio
async def test_expiry_warning_dedup(db):
    from mirza.jobs.expiry import check_expiry_warnings
    from mirza.db.models import Invoice
    from datetime import datetime, timedelta, timezone

    class FakeBot:
        sent = []
        async def send_message(self, uid, text): self.sent.append(uid)

    bot = FakeBot()
    async with db() as s:
        # active invoice expiring in 1 day (with 1h buffer to avoid off-by-one)
        inv = Invoice(id="inv1", user_id=1, sold_at=datetime.now(timezone.utc) - timedelta(days=29) + timedelta(hours=1), duration_days=30, service_username="u1", status="active", price=0)
        s.add(inv)
        s.add(User(id=1, ref_code="a"*32, balance=0))
        s.add(BotSetting(key="warn_days", value="1"))
        await s.commit()
        n = await check_expiry_warnings(s, bot)
        assert n == 1
        # second call same day should not re-warn
        n2 = await check_expiry_warnings(s, bot)
        assert n2 == 0
