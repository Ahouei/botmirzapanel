"""x-ui family adapters.

revision="3x-ui"   -> MHSanaei 3x-ui (login session cookie + /panel/api/inbounds)
revision="alireza" -> Alireza0 x-ui single-session API (same shape, different paths)
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from mirza.core.registry import register_panel

from .base import BasePanel, CreateSpec, PanelError, PanelUser
from .http import PanelHTTP, detail_error

_TSID = re.compile(r'"?tsId"?[:=]\s*"?([A-Za-z0-9_-]{6,})')


def _bytes(n: int) -> int:
    return int(n or 0) * 1024**3


class _XUIBase(BasePanel):
    """Shared cookie-login logic for the two x-ui revisions."""

    display_name = "x-ui"
    login_path = "/login"
    api_list = "/panel/api/inbounds/list"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.http = PanelHTTP(config["url"])
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self._cookie: str | None = None

    async def authenticate(self) -> None:
        if self._cookie:
            return
        status, text = await self.http.request(
            "POST",
            self.login_path,
            data={"username": self.username, "password": self.password},
            expect_json=False,
        )
        cookie = self.http._client.cookies.get("3x-ui") or self.http._client.cookies.get(
            "session"
        )
        if status != 200 or not cookie:
            raise PanelError(f"x-ui login failed: {detail_error(text)}")
        self._cookie = cookie

    async def _call(self, method: str, path: str, **kw) -> Any:
        await self.authenticate()
        status, body = await self.http.request(
            method, path, headers={"Cookie": f"session={self._cookie}"}, **kw
        )
        if status == 401 or status == 403:
            self._cookie = None
            await self.authenticate()
            status, body = await self.http.request(
                method, path, headers={"Cookie": f"session={self._cookie}"}, **kw
            )
        if status >= 400:
            raise PanelError(f"x-ui {path}: HTTP {status} {detail_error(body)}")
        return body

    # ---- helpers shared by both revisions -----------------------------
    @staticmethod
    def _parse_client(client_obj: dict[str, Any], inbound_sub: str = "") -> PanelUser:
        expiry = int(client_obj.get("expiryTime") or 0)
        # x-ui uses ms epoch when |value| > 10^12
        exp_dt = (
            datetime.fromtimestamp(expiry / 1000, tz=UTC)
            if abs(expiry) > 10**12 and expiry != 0
            else datetime.fromtimestamp(expiry, tz=UTC) if expiry else None
        )
        total = int(client_obj.get("totalGB") or 0) or None
        used = int(client_obj.get("down") or 0) + int(client_obj.get("up") or 0)
        sub_url = client_obj.get("subUrl") or inbound_sub or None
        return PanelUser(
            username=str(client_obj.get("email") or ""),
            subscription_url=sub_url,
            links=[client_obj] and [],  # links built by caller from inbound settings
            expires_at=exp_dt,
            used_bytes=used,
            total_bytes=total,
            enabled=int(client_obj.get("enable") or 0) == 1,
            raw=client_obj,
        )


@register_panel("x-ui", "3x-ui")
class XUI3Panel(_XUIBase):
    display_name = "3x-ui"
    login_path = "/login"

    async def create_user(self, spec: CreateSpec) -> PanelUser:
        await self.authenticate()
        inbound_id = spec.inbound_id or self.config.get("inbound_id")
        if not inbound_id:
            raise PanelError("no inbound selected for 3x-ui panel")
        client_id = spec.extra.get("client_id") or _uuid_like()
        payload_client = {
            "id": client_id,
            "email": spec.username,
            "limitIp": spec.extra.get("limit_ip", 0),
            "totalGB": _bytes(spec.volume_gb),
            "expiryTime": int(
                (datetime.now(UTC) + timedelta(days=spec.duration_days)).timestamp()
                * 1000
            )
            if spec.duration_days
            else 0,
            "enable": True,
            "tgId": "",
            "subId": spec.extra.get("sub_id") or client_id[:16],
        }
        body = await self._call(
            "POST",
            "/panel/api/inbounds/addClient",
            json={"id": int(inbound_id), "settings": f'{{"clients": [{payload_client}]}}'},
        )
        obj = body.get("obj") or {}
        if body.get("success") is False:
            raise PanelError(f"3x-ui addClient failed: {detail_error(body)}")
        return PanelUser(
            username=spec.username,
            subscription_url=self._sub_url(spec),
            raw=obj,
            total_bytes=_bytes(spec.volume_gb) or None,
        )

    async def get_user(self, username: str) -> PanelUser | None:
        inb = await self._call("GET", self.api_list)
        for ib in inb.get("obj", []):
            settings = _safe_json(ib.get("settings", "{}"))
            for c in settings.get("clients", []):
                if c.get("email") == username:
                    pu = self._parse_client(c, self._sub_base())
                    pu.raw["inbound_id"] = ib.get("id")
                    return pu
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
            raise PanelError(f"user {username} not found on inbound")
        cid = current.raw.get("id")
        inbound_id = current.raw["inbound_id"]
        payload = {
            "id": cid,
            "email": username,
            "totalGB": _bytes(volume_gb) if volume_gb is not None else int(current.total_bytes or 0),
            "expiryTime": int(
                (expires_at if isinstance(expires_at, datetime) else datetime.now() + expires_at).timestamp()
                * 1000
            )
            if expires_at
            else int(current.expires_at.timestamp() * 1000) if current.expires_at else 0,
            "enable": bool(enable) if enable is not None else current.enabled,
        }
        await self._call(
            "POST",
            f"/panel/api/inbounds/updateClient/{cid}",
            json={"id": int(inbound_id), "settings": str(payload).replace("'", '"')},
        )
        return await self.get_user(username) or current

    async def revoke_user(self, username: str) -> None:
        current = await self.get_user(username)
        if current is None:
            return
        await self._call(
            "POST",
            f"/panel/api/inbounds/{current.raw['inbound_id']}/delClient/{current.raw.get('id')}",
        )

    async def stats(self) -> dict[str, Any]:
        body = await self._call("GET", self.api_list)
        inbs = body.get("obj", [])
        traffic = sum(int(i.get("up") or 0) + int(i.get("down") or 0) for i in inbs)
        clients = sum(len(_safe_json(i.get("settings", "{}")).get("clients", [])) for i in inbs)
        return {"inbounds": len(inbs), "clients": clients, "traffic_bytes": traffic}

    def _sub_base(self) -> str:
        base = self.config.get("sub_url_base")
        return base.rstrip("/") if base else ""

    def _sub_url(self, spec: CreateSpec) -> str | None:
        base = self._sub_base()
        sub_id = spec.extra.get("sub_id")
        return f"{base}/sub/{sub_id}" if base and sub_id else None


def _safe_json(s: str) -> dict:
    import json

    try:
        return json.loads(s) if isinstance(s, str) else (s or {})
    except ValueError:
        return {}


def _uuid_like() -> str:
    import uuid

    return str(uuid.uuid4())


@register_panel("x-ui", "alireza")
class XUIAlirezaPanel(XUI3Panel):
    """Alireza0 fork: same endpoints, slightly different auth cookie name."""

    display_name = "x-ui (Alireza)"
