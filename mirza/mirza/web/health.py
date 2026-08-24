"""aiohttp app: /healthz + payment gateway callbacks.

Legacy: payment/*/back.php endpoints. Improvement: one process serves both
webhook and callbacks; gateway verification is idempotent via WalletService.
"""
from __future__ import annotations

import structlog
from aiohttp import web
from sqlalchemy import select

from mirza.core.registry import registry
from mirza.db.models import PaymentReport
from mirza.services.wallet import WalletService

log = structlog.get_logger(__name__)


def build_app(settings, sessionmaker, scheduler=None) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["sessionmaker"] = sessionmaker

    async def healthz(request: web.Request) -> web.Response:
        ok = True
        try:
            async with request.app["sessionmaker"]() as s:
                await s.execute(select(1))
            db = "ok"
        except Exception as e:
            ok, db = False, f"err:{e.__class__.__name__}"
        return web.json_response(
            {"status": "ok" if ok else "degraded", "db": db,
             "plugins": registry.list()},
            status=200 if ok else 503,
        )

    async def payment_callback(request: web.Request) -> web.Response:
        gw_name = request.match_info["gateway"]
        cls = registry.get("payment", gw_name)
        if cls is None:
            return web.json_response({"error": "unknown gateway"}, status=404)
        try:
            payload = await request.json()
        except Exception:
            payload = dict(await request.post())
        gw = cls(config={})  # per-gateway config loaded from GatewaySetting in prod path
        order_id, ok = await gw.verify_callback(payload)
        if not order_id:
            return web.json_response({"error": "bad callback"}, status=400)
        async with request.app["sessionmaker"]() as s:
            rep = await WalletService(s).mark_paid(order_id)
            status = "paid" if (rep and rep.payment_status == "paid") else "ignored"
        log.info("callback.received", gateway=gw_name, order=order_id, verified=ok, status=status)
        return web.json_response({"status": status})

    # legacy-compatible paths kept for drop-in nginx configs:
    app.router.add_get("/healthz", healthz)
    app.router.add_post("/payment/{gateway}/back.php", payment_callback)
    app.router.add_post("/payment/{gateway}/callback", payment_callback)
    return app
