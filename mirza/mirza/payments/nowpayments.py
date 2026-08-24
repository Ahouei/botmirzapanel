"""NowPayments (crypto) gateway. Mirrors payment/nowpayments + nowPayments()/StatusPayment() in functions.php."""
from __future__ import annotations

from typing import Any

import httpx

from mirza.core.registry import register_payment

from .base import BaseGateway, PaymentRequest, PaymentResult


@register_payment("nowpayments", "default")
class NowPaymentsGateway(BaseGateway):
    API = "https://api.nowpayments.io/v1"

    async def create_payment(self, req: PaymentRequest) -> PaymentResult:
        api_key = self.config["api_key"]
        base = self.config["base_url"].rstrip("/")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{self.API}/invoice",
                headers={"x-api-key": api_key},
                json={
                    "price_amount": float(req.amount),
                    "price_currency": self.config.get("currency", "usd"),
                    "pay_currency": req.meta.get("pay_currency") if req.meta else None,
                    "order_id": req.order_id,
                    "order_description": req.description,
                    "success_url": f"{base}/payment/nowpayments/back.php",
                    "cancel_url": base,
                },
            )
        if r.status_code >= 400:
            return PaymentResult(ok=False, message=r.text[:300])
        body = r.json()
        return PaymentResult(
            ok=True,
            pay_url=body.get("invoice_url"),
            gateway_ref=str(body.get("id")),
        )

    async def verify_callback(self, payload: dict[str, Any]) -> tuple[str, bool]:
        """IPN v1: re-check payment status server-side before trusting it."""
        payment_id = payload.get("payment_id")
        if not payment_id:
            return "", False
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{self.API}/payment/{payment_id}",
                headers={"x-api-key": self.config["api_key"]},
            )
        if r.status_code >= 400:
            return "", False
        body = r.json()
        order_id = str(body.get("order_id") or "")
        return order_id, body.get("payment_status") == "finished"
