"""Shared HTTP helper for panel adapters: timeout, retries, JSON errors."""
from __future__ import annotations

from typing import Any

import httpx

from .base import PanelError


class PanelHTTP:
    """Thin httpx wrapper; adapters compose it with their endpoints."""

    def __init__(self, base_url: str, timeout: float = 6.0):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict | None = None,
        data: dict | list | None = None,
        params: dict | None = None,
        auth: tuple[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        try:
            r = await self._client.request(
                method, path, headers=headers, json=json, data=data, params=params, auth=auth
            )
        except httpx.HTTPError as e:
            raise PanelError(f"connection failed: {e.__class__.__name__}") from e
        if expect_json:
            try:
                body = r.json()
            except ValueError:
                body = {"_text": r.text[:500]}
            return r.status_code, body
        return r.status_code, r.text

    async def aclose(self) -> None:
        await self._client.aclose()


def detail_error(body: Any) -> str:
    """Extract a human-safe error message from common panel JSON shapes."""
    if isinstance(body, dict):
        d = body.get("detail") or body.get("message") or body.get("error")
        if isinstance(d, dict):
            return str(d)
        if d:
            return str(d)
    if isinstance(body, str):
        return body[:200]
    return str(body)[:200]
