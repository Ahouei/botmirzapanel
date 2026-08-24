"""WGDashboard adapter (WireGuard)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mirza.core.registry import register_panel

from .base import BasePanel, CreateSpec, PanelError, PanelUser
from .http import PanelHTTP, detail_error


def _bytes(n: int) -> int:
    return int(n or 0) * 1024**3


@register_panel("wgdashboard", "default")
class WGDashPanel(BasePanel):
    display_name = "WGDashboard"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.http = PanelHTTP(config["url"])
        self.wg_key = config.get("api_key") or config.get("password", "")
        self.configuration = config.get("inbound_id") or "wg0"

    def _h(self) -> dict[str, str]:
        return {"wg-dashboard-apikey": self.wg_key}

    async def authenticate(self) -> None:
        status, body = await self.http.request(
            "GET", "/api/getWireguardConfigurationInfo",
            params={"configurationName": self.configuration},
            headers=self._h(),
        )
        if status != 200:
            raise PanelError(f"wgdashboard auth failed: {detail_error(body)}")

    async def create_user(self, spec: CreateSpec) -> PanelUser:
        body = await self._call(
            "POST", "/api/addPeer",
            headers=self._h(),
            json={
                "configurationName": self.configuration,
                "publicKey": spec.extra.get("public_key"),
                "allowedIp": [],
                "endpointAllowedIp": "0.0.0.0/0",
                "name": spec.username,
                "presharedKey": spec.extra.get("preshared_key"),
            },
        )
        if body.get("status") is False:
            raise PanelError(f"addPeer failed: {detail_error(body)}")
        peer = (body.get("data") or {}).get("id")
        return PanelUser(
            username=spec.username,
            total_bytes=_bytes(spec.volume_gb) or None,
            raw={"peer": peer},
        )

    async def get_user(self, username: str) -> PanelUser | None:
        info = await self._call(
            "GET", "/api/getWireguardConfigurationInfo",
            params={"configurationName": self.configuration},
            headers=self._h(),
        )
        for p in (info.get("data") or {}).get("peers", []):
            if p.get("name") == username:
                return PanelUser(
                    username=username,
                    used_bytes=int(p.get("transmit") or 0) + int(p.get("receive") or 0),
                    enabled=bool(p.get("enabled")),
                    raw=p,
                )
        return None

    async def update_user(
        self,
        username: str,
        *,
        volume_gb: int | None = None,
        expires_at: datetime | timedelta | None = None,
        enable: bool | None = None,
    ) -> PanelUser:
        current = await self.get_user(username)
        if current is None:
            raise PanelError(f"peer {username} not found")
        payload: dict[str, Any] = {"configurationName": self.configuration, "peer": current.raw.get("publicKey")}
        if enable is not None:
            payload["enable"] = enable
        await self._call("POST", "/api/togglePeer", headers=self._h(), json=payload)
        return current

    async def revoke_user(self, username: str) -> None:
        current = await self.get_user(username)
        if not current:
            return
        await self._call(
            "POST", "/api/deletePeers",
            headers=self._h(),
            json={
                "configurationName": self.configuration,
                "peers": [current.raw.get("publicKey")],
            },
        )

    async def stats(self) -> dict[str, Any]:
        info = await self._call(
            "GET", "/api/getWireguardConfigurationInfo",
            params={"configurationName": self.configuration},
            headers=self._h(),
        )
        data = info.get("data", {})
        peers = data.get("peers", [])
        return {
            "configuration": self.configuration,
            "peers": len(peers),
            "traffic_bytes": sum(int(p.get("totalReceive", 0)) + int(p.get("totalTransmit", 0)) for p in peers),
        }
