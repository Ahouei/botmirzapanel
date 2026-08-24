"""Shared HTTP helper for panel adapters: timeout, retries, circuit-breaker-lite."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import PanelError

# per-process failure counters for circuit-breaker-lite (panel url -> (fail_count, last_fail_ts))
_failures: dict[str, tuple[int, float]] = {}
CIRCUIT_THRESHOLD = 5
CIRCUIT_COOLDOWN_S = 60


class PanelHTTP:
    """Thin httpx wrapper with retry + circuit-breaker-lite."""

    def __init__(self, base_url: str, timeout: float = 6.0, retries: int = 1):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    def _circuit_open(self) -> bool:
        cnt, ts = _failures.get(self.base_url, (0, 0.0))
        if cnt >= CIRCUIT_THRESHOLD and (time.monotonic() - ts) < CIRCUIT_COOLDOWN_S:
            return True
        if cnt >= CIRCUIT_THRESHOLD and (time.monotonic() - ts) >= CIRCUIT_COOLDOWN_S:
            _failures.pop(self.base_url, None)
        return False

    def _record_success(self) -> None:
        _failures.pop(self.base_url, None)

    def _record_failure(self) -> None:
        cnt, _ = _failures.get(self.base_url, (0, 0.0))
        _failures[self.base_url] = (cnt + 1, time.monotonic())

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
        if self._circuit_open():
            raise PanelError(f"circuit open for {self.base_url} (cooldown {CIRCUIT_COOLDOWN_S}s)")
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = await self._client.request(
                    method, path, headers=headers, json=json, data=data, params=params, auth=auth
                )
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < self.retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                self._record_failure()
                raise PanelError(f"connection failed: {e.__class__.__name__}: {e}") from e
            # 429 / 5xx are retryable once
            if r.status_code in (429, 502, 503, 504) and attempt < self.retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            self._record_success()
            if expect_json:
                try:
                    body = r.json()
                except ValueError:
                    body = {"_text": r.text[:500]}
                return r.status_code, body
            return r.status_code, r.text
        # exhausted retries
        if last_exc:
            raise PanelError(f"connection failed after {self.retries+1} tries: {last_exc}") from last_exc
        raise PanelError("request failed after retries")

    async def aclose(self) -> None:
        await self._client.aclose()


def detail_error(body: Any) -> str:
    """Extract a human-safe error message from common panel JSON shapes."""
    if isinstance(body, dict):
        d = body.get("detail") or body.get("message") or body.get("error") or body.get("msg")
        if isinstance(d, list) and d:
            d = d[0].get("msg") if isinstance(d[0], dict) else str(d[0])
        if isinstance(d, dict):
            return str(d.get("msg") or d.get("detail") or d)[:300]
        if d:
            return str(d)[:300]
        # validation error array
        if "errors" in body:
            return str(body["errors"])[:300]
    if isinstance(body, str):
        return body[:300]
    return str(body)[:300]
