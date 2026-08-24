"""s-ui (sing-box panel) adapter."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mirza.core.registry import register_panel

from .base import BasePanel, CreateSpec, PanelError, PanelUser
from .http import PanelHTTP, detail_error


@register_panel("s-ui", "default")
class SUIPanel(BasePanel):
    display_name = "s-ui"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.http = PanelHTTP(config["url"])
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self._cookie: str | None = None

    async def authenticate(self) -> None:
        if self._cookie:
            return
        status, body = await self.http.request(
            "POST", "/app/api/login",
            json={"username": self.username, "password": self.password},
        )
        cookie = self.http._client.cookies.get("session")
        if status != 200 or not cookie:
            raise PanelError(f"s-ui login failed: {detail_error(body)}")
        self._cookie = cookie

    async def _call(self, method: str, path: str, **kw) -> Any:
        await self.authenticate()
        status, body = await self.http.request(
            method, path,
            headers={"Cookie": f"session={self._cookie}"}, **kw
        )
        if status >= 400:
            raise PanelError(f"s-ui {path}: HTTP {status} {detail_error(body)}")
        return body

    async def create_user(self, spec: CreateSpec) -> PanelUser:
        await self.authenticate()
        # s-ui stores clients as part of inbound config; API: /app/inbounds save
        payload = {
            "name": spec.username,
            "config": spec.extra.get("singbox_config", {}),
        }
        await self._call("POST", "/app/createClient", json=payload)
        return PanelUser(
            username=spec.username,
            links=spec.extra.get("links", []),
            subscription_url=self.config.get("sub_url_base"),
        )

    async def get_user(self, username: str) -> PanelUser | None:
        clients = await self._call("GET", "/app/clients")
        for c in clients or []:
            if c.get("name") == username:
                return PanelUser(username=username, raw=c)
        return None

    async def update_user(
        self,
        username: str,
        *,
        volume_gb: int | None = None,
        expires_at: datetime | timedelta | None = None,
        enable: bool | None = None,
    ) -> PanelUser:
        raise PanelError("s-ui quota edits are handled at inbound level; not supported yet")

    async def revoke_user(self, username: str) -> None:
        current = await self.get_user(username)
        if not current:
            return
        await self._call("POST", "/app/deleteClient", json={"id": current.raw.get("id")})

    async def stats(self) -> dict[str, Any]:
        return await self._call("GET", "/app/stat")
