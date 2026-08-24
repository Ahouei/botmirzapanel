"""aiohttp app: /healthz + payment gateway callbacks.

Legacy: payment/*/back.php endpoints. Improvement: one process serves both
webhook and callbacks; gateway verification is idempotent via WalletService.
"""
from __future__ import annotations

import time

import structlog
from aiohttp import web
from sqlalchemy import select

from mirza.core.registry import registry
from mirza.services.wallet import WalletService

log = structlog.get_logger(__name__)
_started = time.monotonic()


def build_app(settings, sessionmaker, scheduler=None) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["sessionmaker"] = sessionmaker
    app["scheduler"] = scheduler

    async def healthz(request: web.Request) -> web.Response:
        checks: dict = {"status": "ok", "uptime_s": int(time.monotonic() - _started), "version": __import__("mirza").__version__}
        ok = True
        # db
        try:
            async with request.app["sessionmaker"]() as s:
                await s.execute(select(1))
            checks["db"] = "ok"
        except Exception as e:
            ok = False
            checks["db"] = f"err:{e.__class__.__name__}:{str(e)[:120]}"
        # bot token present
        checks["bot_configured"] = bool(settings.telegram.bot_token)
        # scheduler
        sched = request.app.get("scheduler")
        if sched is not None:
            try:
                checks["jobs"] = [j.id for j in sched.get_jobs()]
            except Exception:
                checks["jobs"] = "unknown"
        checks["plugins"] = registry.list()
        if not ok:
            checks["status"] = "degraded"
        return web.json_response(checks, status=200 if ok else 503)

    async def ready(request: web.Request) -> web.Response:
        # k8s-style readiness: only db check
        try:
            async with request.app["sessionmaker"]() as s:
                await s.execute(select(1))
            return web.json_response({"ready": True})
        except Exception as e:
            return web.json_response({"ready": False, "error": str(e)[:200]}, status=503)

    async def payment_callback(request: web.Request) -> web.Response:
        gw_name = request.match_info["gateway"]
        cls = registry.get("payment", gw_name)
        if cls is None:
            return web.json_response({"error": "unknown gateway", "available": [n for _, n, _ in registry.list("payment")]}, status=404)
        # parse payload (json or form)
        try:
            ctype = request.headers.get("Content-Type", "")
            if "application/json" in ctype:
                payload = await request.json()
            else:
                payload = dict(await request.post())
                # also merge query string
                payload.update(dict(request.query))
        except Exception as e:
            return web.json_response({"error": f"bad payload: {e}"}, status=400)
        # load gateway config from DB
        cfg: dict = {}
        try:
            async with request.app["sessionmaker"]() as s:
                from mirza.db.models import GatewaySetting

                rows = (await s.execute(select(GatewaySetting).where(GatewaySetting.gateway == gw_name))).scalars().all()
                cfg = {r.key: r.value for r in rows}
        except Exception:
            pass
        gw = cls(config=cfg)
        try:
            order_id, verified = await gw.verify_callback(payload)
        except Exception as e:
            log.warning("callback.verify_error", gateway=gw_name, err=str(e))
            return web.json_response({"error": "verify failed"}, status=500)
        if not order_id:
            return web.json_response({"error": "bad callback: no order_id"}, status=400)
        # idempotent mark-paid only if gateway verified
        if verified:
            try:
                async with request.app["sessionmaker"]() as s:
                    rep = await WalletService(s).mark_paid(order_id)
                    status_s = "paid" if (rep and rep.payment_status == "paid") else "ignored"
            except Exception as e:
                log.error("callback.mark_paid_failed", order=order_id, err=str(e))
                return web.json_response({"error": "internal"}, status=500)
        else:
            status_s = "not_verified"
        log.info("callback.received", gateway=gw_name, order=order_id, verified=verified, status=status_s)
        return web.json_response({"status": status_s, "order_id": order_id, "verified": verified})

    app.router.add_get("/healthz", healthz)
    app.router.add_get("/readyz", ready)
    app.router.add_get("/health", healthz)
    app.router.add_get("/metrics", metrics)
    app.router.add_post("/payment/{gateway}/back.php", payment_callback)
    app.router.add_post("/payment/{gateway}/callback", payment_callback)
    app.router.add_post("/callback/{gateway}", payment_callback)
    return app


async def metrics(request: web.Request) -> web.Response:
    """Prometheus exposition (no extra deps)."""
    lines: list[str] = []
    try:
        async with request.app["sessionmaker"]() as s:
            from sqlalchemy import func as _func

            from mirza.db.models import Invoice, PaymentReport, User

            users = (await s.execute(select(_func.count()).select_from(User))).scalar() or 0
            invoices = (await s.execute(select(_func.count()).select_from(Invoice))).scalar() or 0
            active = (await s.execute(select(_func.count()).select_from(Invoice).where(Invoice.status == "active"))).scalar() or 0
            paid = (await s.execute(select(_func.coalesce(_func.sum(PaymentReport.price), 0)).where(PaymentReport.payment_status == "paid"))).scalar() or 0
            pending_cards = (await s.execute(select(_func.count()).select_from(PaymentReport).where(PaymentReport.gateway == "card", PaymentReport.payment_status == "pending"))).scalar() or 0
            lines.extend(
                [
                    "# HELP mirza_users Total users",
                    "# TYPE mirza_users gauge",
                    f"mirza_users {users}",
                    "# HELP mirza_invoices Total invoices",
                    "# TYPE mirza_invoices gauge",
                    f"mirza_invoices {invoices}",
                    "# HELP mirza_active_invoices Active services",
                    "# TYPE mirza_active_invoices gauge",
                    f"mirza_active_invoices {active}",
                    "# HELP mirza_paid_toman Sum of paid topups (toman)",
                    "# TYPE mirza_paid_toman gauge",
                    f"mirza_paid_toman {paid}",
                    "# HELP mirza_pending_card_receipts Pending card receipts",
                    "# TYPE mirza_pending_card_receipts gauge",
                    f"mirza_pending_card_receipts {pending_cards}",
                    "# HELP mirza_uptime_seconds Bot uptime",
                    "# TYPE mirza_uptime_seconds gauge",
                    f"mirza_uptime_seconds {int(time.monotonic() - _started)}",
                ]
            )
            # panel probe gauges (best-effort, no network)
            try:
                from mirza.db.models import PanelServer

                panels = (await s.execute(select(_func.count()).select_from(PanelServer))).scalar() or 0
                enabled = (await s.execute(select(_func.count()).select_from(PanelServer).where(PanelServer.enabled.is_(True)))).scalar() or 0
                lines.extend([f"mirza_panels {panels}", f"mirza_panels_enabled {enabled}"])
            except Exception:
                pass
    except Exception as e:
        lines.append(f"# metrics error: {e}")
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain; version=0.0.4")
