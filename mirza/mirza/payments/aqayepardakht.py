"""Aqayepardakht (Iranian gateway). Mirrors payment/aqayepardakht/*."""
from __future__ import annotations

import httpx

from mirza.core.registry import register_payment

from .base import BaseGateway, PaymentRequest, PaymentResult


@register_payment("aqayepardakht", "default")
class AqayeGateway(BaseGateway):
    API = "https://panel.aqayepardakht.ir/api/v2"

    # callback POSTs: pin, amount, invoice_id -> create; then verify with transid
    async def create_payment(self, req: PaymentRequest) -> PaymentResult:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self.API}/create",
                json={
                    "pin": self.config["merchant_pin"],
                    "amount": str(int(req.amount)),  # toman
                    "callback": self.config["callback_url"],
                    "invoice_id": req.order_id,
                    "description": req.description[:100],
                },
            )
        body = r.json()
        if body.get("code") != "1":
            return PaymentResult(ok=False, message=f"aqaye create: {body.get('code')}")
        return PaymentResult(
            ok=True,
            pay_url=body.get("url"),
            gateway_ref=body.get("transid"),
        )

    async def verify_callback(self, payload: dict) -> tuple[str, bool]:
        """Callback sends transid; we must verify server-side."""
        transid = payload.get("transid")
        if not transid:
            return payload.get("invoice_id", ""), False
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self.API}/verify",
                json={
                    "pin": self.config["merchant_pin"],
                    "amount": payload.get("amount"),
                    "transid": transid,
                },
            )
        body = r.json()
        ok = body.get("code") == "1"
        return payload.get("invoice_id", ""), ok
