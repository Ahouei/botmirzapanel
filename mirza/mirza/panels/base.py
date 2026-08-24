"""Panel Protocol - the plugin contract every VPN backend adapter must satisfy.

This is the heart of extensibility: a new panel type or revision = one class
implementing this protocol + @register_panel. Nothing else changes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


class PanelError(Exception):
    """Base for adapter failures; message is safe to show admins."""


@dataclass
class PanelUser:
    username: str
    subscription_url: str | None = None
    links: list[str] = field(default_factory=list)
    expires_at: datetime | None = None
    used_bytes: int = 0
    total_bytes: int | None = None  # None = unlimited
    enabled: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreateSpec:
    username: str
    volume_gb: int                      # 0 => unlimited
    duration_days: int                  # 0 => unlimited
    on_hold: bool = False               # start counting on first use
    inbound_id: str | None = None       # panel-specific inbound selector
    protocol_hint: str | None = None    # vless/vmess/trojan/wireguard...
    extra: dict[str, Any] = field(default_factory=dict)


class BasePanel(abc.ABC):
    """Async contract. Config comes from PanelServer row (url, creds, extra...)."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    #: human-readable name shown in admin UIs
    display_name: str = "abstract"

    @abc.abstractmethod
    async def authenticate(self) -> None:
        """Login/token fetch; must cache internally and be idempotent."""

    @abc.abstractmethod
    async def create_user(self, spec: CreateSpec) -> PanelUser:
        """Provision the service; raise PanelError on any failure."""

    @abc.abstractmethod
    async def get_user(self, username: str) -> PanelUser | None:
        ...

    @abc.abstractmethod
    async def update_user(
        self,
        username: str,
        *,
        volume_gb: int | None = None,
        expires_at: datetime | timedelta | None = None,
        enable: bool | None = None,
    ) -> PanelUser:
        ...

    @abc.abstractmethod
    async def revoke_user(self, username: str) -> None:
        """Delete/disable the service (admin 'remove user' / expiry cleanup)."""

    @abc.abstractmethod
    async def stats(self) -> dict[str, Any]:
        """System-level stats for admin dashboard/health checks."""
