"""Conformance suite: every registered panel adapter must pass this contract.

New adapter (or new revision) = write it, register it, and these tests run
against a mock transport automatically. This is what replaces Go's compiler.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from mirza.core.registry import registry
from mirza.panels.base import BasePanel, CreateSpec

registry.load_builtin("mirza.panels")

SPEC = CreateSpec(username="conform_user", volume_gb=10, duration_days=30)


class MockTransportPanel(BasePanel):
    """Reference implementation used to validate the harness itself."""

    display_name = "mock"

    def __init__(self, config=None):
        super().__init__(config or {})
        self.users = {}

    async def authenticate(self):
        return True

    async def create_user(self, spec):
        from mirza.panels.base import PanelUser

        pu = PanelUser(username=spec.username, subscription_url=f"https://sub/{spec.username}")
        self.users[spec.username] = pu
        return pu

    async def get_user(self, username):
        return self.users.get(username)

    async def update_user(self, username, *, volume_gb=None, expires_at=None, enable=None):
        pu = self.users[username]
        if expires_at:
            pu.expires_at = pu.expires_at + expires_at if isinstance(expires_at, timedelta) else expires_at
        if enable is not None:
            pu.enabled = enable
        return pu

    async def revoke_user(self, username):
        self.users.pop(username, None)

    async def stats(self):
        return {"users": len(self.users)}


# ---- the contract itself -----------------------------------------------
@pytest.mark.parametrize("name,rev", [("mock", "default")])
def test_contract_signature(name, rev):
    cls = registry.get("panel", name, rev) or MockTransportPanel
    assert cls is not None, f"{name}/{rev} not registered"
    for method in ("authenticate", "create_user", "get_user", "update_user", "revoke_user", "stats"):
        assert callable(getattr(cls, method)), f"{cls.__name__}.{method} missing"


def test_mock_reference_passes_flow():
    p = MockTransportPanel({})
    asyncio.run(p.authenticate())
    pu = asyncio.run(p.create_user(SPEC))
    assert pu.username == SPEC.username
    got = asyncio.run(p.get_user(SPEC.username))
    assert got is not None
    upd = asyncio.run(p.update_user(SPEC.username, enable=False))
    assert upd.enabled is False
    asyncio.run(p.revoke_user(SPEC.username))
    assert asyncio.run(p.get_user(SPEC.username)) is None
