"""MikroTik RouterOS REST API adapter."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mirza.core.registry import register_panel

from .base import BasePanel, CreateSpec, PanelError, PanelUser
from .http import PanelHTTP, detail_error


@register_panel("mikrotik", "rest")
class MikrotikPanel(BasePanel):
    display_name = "MikroTik"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.http = PanelHTTP(config["url"], timeout=8.0)
        self.user = config.get("username", "")
        self.pw = config.get("password", "")

    async def authenticate(self) -> None:
        status, body = await self.http.request(
            "GET", "/rest/system/resource",
            auth=(self.user, self.pw),
        )
        if status != 200:
            raise PanelError(f"mikrotik auth failed: HTTP {status} {detail_error(body)}")

    async def _call(self, method: str, path: str, **kw) -> Any:
        status, body = await self.http.request(method, path, auth=(self.user, self.pw), **kw)
        if status >= 400:
            raise PanelError(f"mikrotik {path}: HTTP {status} {detail_error(body)}")
        return body

    async def create_user(self, spec: CreateSpec) -> PanelUser:
        secret = {
            "name": spec.username,
            "password": spec.extra.get("secret_password", ""),
            "profile": spec.inbound_id or spec.extra.get("profile", "default"),
            "comment": f"mirza:{spec.username}",
        }
        await self._call("PUT", "/rest/ppp/secret", json=secret)
        return PanelUser(username=spec.username, raw=secret)

    async def get_user(self, username: str) -> PanelUser | None:
        secrets = await self._call("GET", "/rest/ppp/secret")
        for s in secrets or []:
            if s.get("name") == username:
                active = await self._active_session(username)
                return PanelUser(
                    username=username,
                    enabled=s.get("disabled") != "true",
                    raw={"secret": s, "session": active},
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
            raise PanelError(f"{username} not found")
        sid = current.raw["secret"][".id"]
        patch: dict[str, Any] = {}
        if enable is not None:
            patch["disabled"] = "no" if enable else "yes"
        if patch:
            await self._call("PATCH", f"/rest/ppp/secret/{sid}", json=patch)
        return await self.get_user(username) or current

    async def revoke_user(self, username: str) -> None:
        current = await self.get_user(username)
        if not current:
            return
        await self._call("DELETE", f"/rest/ppp/secret/{current.raw['secret']['.id']}")

    async def stats(self) -> dict[str, Any]:
        res = await self._call("GET", "/rest/system/resource")
        sessions = await self._call("GET", "/rest/ppp/active")
        return {
            "cpu_load": res.get("cpu-load"),
            "free_memory_mb": int(res.get("free-memory", 0)) // 1024 // 1024,
            "active_sessions": len(sessions or []),
        }

    async def _active_session(self, username: str) -> dict | None:
        try:
            actives = await self._call("GET", "/rest/ppp/active")
            for a in actives or []:
                if a.get("name") == username:
                    return a
        except PanelError:
            pass
        return None
