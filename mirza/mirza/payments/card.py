"""Card-to-card manual payment: user sends receipt photo, admin approves.

Legacy: cron/croncard.php + admin 'cart_to_cart' flows.
Improvement: receipts are stored as Telegram file_ids, admin gets approve/reject
inline buttons instead of text commands.
"""
from __future__ import annotations

from mirza.core.registry import register_payment

from .base import BaseGateway, PaymentRequest, PaymentResult


@register_payment("card", "manual")
class CardToCardGateway(BaseGateway):
    async def create_payment(self, req: PaymentRequest) -> PaymentResult:
        # No external API; the bot shows card info and waits for receipt.
        return PaymentResult(ok=True, pay_url=None, gateway_ref=req.order_id)

    async def verify_callback(self, payload: dict) -> tuple[str, bool]:
        """Approval happens via admin button -> services.payments.approve_receipt."""
        order_id = str(payload.get("order_id", ""))
        approved = payload.get("approved") is True
        return order_id, approved
