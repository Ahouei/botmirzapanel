"""Purchase service: the core sale flow.

Legacy spread across index.php (getdata->getprice->payment) + panels.php
ManagePanel.createUser. Consolidated into one audited use-case.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mirza.core.registry import registry
from mirza.db.models import Invoice, PanelServer, Product, User

log = structlog.get_logger(__name__)


class PurchaseError(Exception):
    pass


@dataclass
class ProvisionResult:
    invoice: Invoice
    panel_user: Any  # PanelUser from adapter


def gen_service_username(user_id: int, method: str = "random") -> str:
    if method == "userid":
        return f"mirza{user_id}{secrets.token_hex(2)}"
    return "m" + secrets.token_hex(8)


class PurchaseService:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def _panel_for(self, name: str) -> tuple[BasePanelLike, PanelServer]:
        row = (
            await self.s.execute(select(PanelServer).where(PanelServer.name == name))
        ).scalar_one_or_none()
        if row is None or not row.enabled:
            raise PurchaseError(f"panel '{name}' unavailable")
        cls = registry.get("panel", row.plugin, row.revision)
        if cls is None:
            raise PurchaseError(f"no plugin for {row.plugin}/{row.revision}")
        cfg = {
            "url": row.url,
            "username": row.username,
            "password": row.password,
            "sub_url_base": row.sub_url_base,
            "inbound_id": row.inbound_id,
        }
        cfg.update(row.extra or {})
        inst = cls(config=cfg)
        await inst.authenticate()
        return inst, row

    async def provision(
        self,
        user_id: int,
        *,
        product: Product | None = None,
        custom: dict[str, Any] | None = None,
        is_test: bool = False,
    ) -> ProvisionResult:
        """Create service on the target panel + local invoice. One transaction."""
        custom = custom or {}
        location = product.location if product else custom["location"]
        volume = product.volume_gb if product else int(custom.get("volume_gb", 0))
        days = product.duration_days if product else int(custom.get("duration_days", 30))
        price = product.price if product else int(custom.get("price", 0))

        panel_api, panel_row = await self._panel_for(location)
        method = panel_row.username_method or "random"
        svc_username = gen_service_username(user_id, method)

        spec_cls = __import__("mirza.panels.base", fromlist=["CreateSpec"]).CreateSpec
        spec = spec_cls(
            username=svc_username,
            volume_gb=volume,
            duration_days=days,
            on_hold=panel_row.on_hold and not is_test,
            inbound_id=panel_row.inbound_id,
        )
        try:
            panel_user = await panel_api.create_user(spec)
        except Exception as e:
            raise PurchaseError(f"panel rejected: {e}") from e

        inv = Invoice(
            id="inv" + secrets.token_hex(8),
            user_id=user_id,
            product_name=product.name if product else ("usertest" if is_test else custom.get("name", "custom")),
            panel_name=location,
            sold_at=datetime.now(timezone.utc),
            price=price,
            volume_gb=volume,
            duration_days=days,
            service_username=svc_username,
            config_payload={
                "subscription_url": panel_user.subscription_url,
                "links": panel_user.links,
                "is_test": is_test,
            },
            status="active",
        )
        self.s.add(inv)
        await self.s.commit()
        log.info("purchase.provisioned", invoice=inv.id, user=user_id, panel=location, test=is_test)
        return ProvisionResult(invoice=inv, panel_user=panel_user)

    async def renew(self, invoice_id: str, *, add_days: int, add_gb: int = 0) -> Invoice:
        inv = await self.s.get(Invoice, invoice_id)
        if inv is None:
            raise PurchaseError("invoice not found")
        panel_api, _ = await self._panel_for(inv.panel_name)
        new_exp = (inv.sold_at or datetime.now(timezone.utc)) + timedelta(
            days=add_days
        )
        # remaining time credit: extend from max(now, current expiry)
        current = await panel_api.get_user(inv.service_username)
        if current and current.expires_at and current.expires_at > datetime.now(timezone.utc):
            new_exp = current.expires_at + timedelta(days=add_days)
        vol = (inv.volume_gb or 0) + add_gb
        await panel_api.update_user(
            inv.service_username, expires_at=new_exp, volume_gb=vol or None
        )
        inv.duration_days = (inv.duration_days or 0) + add_days
        inv.volume_gb = vol
        inv.status = "active"
        self.s.add(AuditLog(action="purchase.renew", target=invoice_id,
                            detail={"add_days": add_days, "add_gb": add_gb}))
        await self.s.commit()
        return inv

    async def cancel(self, invoice_id: str, *, by_admin: bool = False) -> None:
        inv = await self.s.get(Invoice, invoice_id)
        if inv is None:
            raise PurchaseError("invoice not found")
        try:
            panel_api, _ = await self._panel_for(inv.panel_name)
            await panel_api.revoke_user(inv.service_username)
        except PurchaseError:
            if not by_admin:
                raise
        inv.status = "deleted"
        await self.s.commit()


# typing-only alias to dodge circular import in annotations
from mirza.panels.base import BasePanel as BasePanelLike  # noqa: E402,F401
from mirza.db.models import AuditLog  # noqa: E402
