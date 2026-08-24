import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mirza.db.models import Base, BotSetting, Category, PanelServer, Product, User
from mirza.services.purchase import PurchaseService
from mirza.core.registry import registry

registry.load_builtin("mirza.panels")


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    yield sm
    await engine.dispose()


@pytest.fixture
def mock_panel(monkeypatch):
    from mirza.panels.base import BasePanel, PanelUser, CreateSpec

    class MockPanel(BasePanel):
        display_name = "mock-test"
        async def authenticate(self): pass
        async def create_user(self, spec: CreateSpec) -> PanelUser:
            return PanelUser(username=spec.username, subscription_url=f"https://sub/{spec.username}", links=[f"vless://{spec.username}@mock"])
        async def get_user(self, username): return None
        async def update_user(self, username, **kw): from mirza.panels.base import PanelUser; return PanelUser(username=username)
        async def revoke_user(self, username): pass
        async def stats(self): return {"ok": True}

    # register under a temp name
    try:
        registry.register("panel", "mocktest", "default")(MockPanel)
    except ValueError:
        pass
    return MockPanel
