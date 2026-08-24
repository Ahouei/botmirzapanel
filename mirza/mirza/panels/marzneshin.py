"""Marzneshin adapter (korthix-style API, token auth)."""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from mirza.core.registry import register_panel

from .base import BasePanel, CreateSpec, PanelError, PanelUser
from .http import PanelHTTP, detail_error


def _bytes(n: int) -> int:
    return int(n or 0) * 1024**3


@register_panel("marzneshin", "default")
class MarzneshinPanel(BasePanel):
    display_name = "Marzneshin"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.http = PanelHTTP(config["url"])
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self._token: str | None = None
        self._token_at: float = 0.0

    async def authenticate(self) -> None:
        if self._token and (time.time() - self._token_at) < 3000:
            return
        status, body = await self.http.request(
            "POST", "/api/admins/token",
            data={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status != 200 or not isinstance(body, dict) or "access_token" not in body:
            raise PanelError(f"marzneshin auth failed: {detail_error(body)}")
        self._token = body["access_token"]
        self._token_at = time.time()

    async def _call(self, method: str, path: str, **kw) -> Any:
        await self.authenticate()
        status, body = await self.http.request(
            method, path,
            headers={"Authorization": f"Bearer {self._token}"}, **kw
        )
        if status >= 400:
            raise PanelError(f"marzneshin {path}: {detail_error(body)}")
        return body

    async def create_user(self, spec: CreateSpec) -> PanelUser:
        payload = {
            "username": spec.username,
            "data_limit": _bytes(spec.volume_gb) or None,
            "expire_on": (
                datetime.now(UTC) + timedelta(days=spec.duration_days)
            ).isoformat() if spec.duration_days else None,
            "service_ids": [int(spec.inbound_id)] if spec.inbound_id else [],
        }
        body = await self._call("POST", "/api/users", json=payload)
        return self._to_panel_user(body)

    async def get_user(self, username: str) -> PanelUser | None:
        try:
            body = await self._call("GET", f"/api/users/{username}")
        except PanelError as e:
            if "404" in str(e):
                return None
            raise
        return self._to_panel_user(body)

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
            raise PanelError(f"user {username} not found")
        payload: dict[str, Any] = {
            "username": username,
            "service_ids": current.raw.get("service_ids", []),
        }
        if volume_gb is not None:
            payload["data_limit"] = _bytes(volume_gb) or None
        if isinstance(expires_at, timedelta):
            expires_at = datetime.now(UTC) + expires_at
        if expires_at is not None:
            payload["expire_on"] = expires_at.isoformat()
        if enable is not None:
            payload["enabled"] = enable
        body = await self._call("PUT", f"/api/users/{username}", json=payload)
        return self._to_panel_user(body)

    async def revoke_user(self, username: str) -> None:
        try:
            await self._call("DELETE", f"/api/users/{username}")
        except PanelError as e:
            if "404" not in str(e):
                raise

    async def stats(self) -> dict[str, Any]:
        body = await self._call("GET", "/api/system")
        nodes = (body or {}).get("nodes", [])
        return {"system": body, "nodes_online": sum(1 for n in nodes if n.get("is_online"))}

    def _to_panel_user(self, body: dict[str, Any]) -> PanelUser:
        u = body.get("user", body)
        sub = body.get("subscription_url") or u.get("subscription_url") or ""
        if sub.startswith("/"):
            base = self.config.get("sub_url_base") or self.config["url"]
            sub = base.rstrip("/") + "/" + sub.lstrip("/")
        exp = u.get("expire_on")
        used = u.get("used_traffic") or 0
        total = u.get("data_limit") or None
        return PanelUser(
            username=u.get("username", ""),
            subscription_url=sub or None,
            links=[sub] if sub else [],
            expires_at=datetime.fromisoformat(exp.replace("Z", "+00:00")) if exp else None,
            used_bytes=int(used),
            total_bytes=int(total) if total else None,
            enabled=bool(u.get("enabled", True)),
            raw=body,
        )
