"""Marzban adapter (revision=default: classic marzban)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from mirza.core.registry import register_panel

from .base import BasePanel, CreateSpec, PanelError, PanelUser
from .http import PanelHTTP, detail_error


def _gb(n: int) -> int:
    return int(n or 0) * 1024**3


def _iso(dt: datetime | timedelta | None) -> int | None:
    """Marzban wants epoch ms-ish (seconds since epoch as int)."""
    if dt is None:
        return None
    if isinstance(dt, timedelta):
        dt = datetime.now(timezone.utc) + dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@register_panel("marzban", "classic")
class MarzbanPanel(BasePanel):
    display_name = "Marzban"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.http = PanelHTTP(config["url"])
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self._token: str | None = None
        self._token_at: float = 0.0

    # ---- auth ---------------------------------------------------------
    async def authenticate(self) -> None:
        # token valid ~1h in marzban; refresh when older than 50 min
        if self._token and (time.time() - self._token_at) < 3000:
            return
        status, body = await self.http.request(
            "POST",
            "/api/admin/token",
            data={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status != 200 or not isinstance(body, dict) or "access_token" not in body:
            raise PanelError(f"marzban auth failed: {detail_error(body)}")
        self._token = body["access_token"]
        self._token_at = time.time()

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise PanelError("not authenticated")
        return {"Authorization": f"Bearer {self._token}"}

    async def _call(self, method: str, path: str, **kw) -> Any:
        await self.authenticate()
        status, body = await self.http.request(
            method, path, headers=self._auth_headers(), **kw
        )
        if status >= 400 and isinstance(body, dict) and str(body.get("detail", "")).startswith(
            "Not authenticated"
        ):
            self._token = None
            await self.authenticate()
            status, body = await self.http.request(
                method, path, headers=self._auth_headers(), **kw
            )
        if status == 404:
            return None
        if status >= 400:
            raise PanelError(f"marzban {method} {path}: {detail_error(body)}")
        return body

    # ---- contract -----------------------------------------------------
    async def create_user(self, spec: CreateSpec) -> PanelUser:
        await self.authenticate()
        payload: dict[str, Any] = {
            "username": spec.username,
            "proxies": spec.extra.get("proxies", {}),
            "inbounds": spec.extra.get("inbounds", {}),
            "data_limit": _gb(spec.volume_gb) or None,
            "expire": _iso(datetime.now() + timedelta(days=spec.duration_days))
            if spec.duration_days
            else 0,
        }
        if spec.on_hold:
            payload["status"] = "on_hold"
        body = await self._call("POST", "/api/user", json=payload)
        return self._to_panel_user(body)

    async def get_user(self, username: str) -> PanelUser | None:
        body = await self._call("GET", f"/api/user/{username}")
        if body is None:
            return None
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
            raise PanelError(f"user {username} not found on panel")
        payload: dict[str, Any] = {}
        if volume_gb is not None:
            payload["data_limit"] = _gb(volume_gb) or None
        if expires_at is not None:
            payload["expire"] = _iso(expires_at)
        if enable is not None:
            payload["status"] = "active" if enable else "disabled"
        body = await self._call("PUT", f"/api/user/{username}", json=payload)
        return self._to_panel_user(body)

    async def revoke_user(self, username: str) -> None:
        await self.authenticate()
        status, _ = await self.http.request(
            "DELETE", f"/api/user/{username}", headers=self._auth_headers()
        )
        if status not in (200, 404):
            raise PanelError(f"revoke {username}: HTTP {status}")

    async def stats(self) -> dict[str, Any]:
        sysinfo = await self._call("GET", "/api/system")
        users = await self._call("GET", "/api/users")
        total = len(users or [])
        active = sum(1 for u in users or [] if u.get("status") == "active")
        return {
            "version": sysinfo.get("version"),
            "total_users": total,
            "active_users": active,
            "bandwidth_used_bytes": (sysinfo.get("outgoing_bandwidth") or 0)
            + (sysinfo.get("incoming_bandwidth") or 0),
        }

    # ---- helpers ------------------------------------------------------
    def _to_panel_user(self, body: dict[str, Any]) -> PanelUser:
        sub = body.get("subscription_url") or ""
        if sub.startswith("/"):  # relative -> absolute using configured base
            base = self.config.get("sub_url_base") or self.config["url"]
            sub = base.rstrip("/") + "/" + sub.lstrip("/")
        exp = body.get("expire") or 0
        return PanelUser(
            username=body.get("username", ""),
            subscription_url=sub or None,
            links=list(body.get("links") or []),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc) if exp else None,
            used_bytes=int(body.get("used_traffic") or 0),
            total_bytes=(int(body["data_limit"]) if body.get("data_limit") else None),
            enabled=body.get("status") == "active",
            raw=body,
        )
