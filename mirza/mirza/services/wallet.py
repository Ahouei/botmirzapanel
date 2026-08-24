"""Wallet service: balance, top-ups, gift codes. (Legacy DirectPayment + Discount.)"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mirza.db.models import AuditLog, Discount, GiftCodeRedemption, PaymentReport, User

log = structlog.get_logger(__name__)


class WalletService:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def add_balance(self, user_id: int, amount: int, *, reason: str, actor_id: int | None = None) -> int:
        res = await self.s.execute(
            update(User).where(User.id == user_id).values(balance=User.balance + amount)
        )
        if res.rowcount == 0:
            raise ValueError(f"user {user_id} not found")
        self.s.add(AuditLog(actor_id=actor_id, action="wallet.add", target=str(user_id),
                            detail={"amount": amount, "reason": reason}))
        await self.s.commit()
        return amount

    async def charge(self, user_id: int, amount: int, *, reason: str) -> bool:
        """Atomic spend; False when insufficient funds."""
        user = await self.s.get(User, user_id)
        if not user or user.balance < amount:
            return False
        user.balance -= amount
        self.s.add(AuditLog(action="wallet.charge", target=str(user_id),
                            detail={"amount": amount, "reason": reason}))
        await self.s.commit()
        return True

    # ---- gift codes ----------------------------------------------------
    async def redeem_gift_code(self, user_id: int, code: str) -> tuple[bool, str]:
        d = (await self.s.execute(select(Discount).where(Discount.code == code))).scalar_one_or_none()
        if d is None:
            return False, "invalid_code"
        now = datetime.now(UTC)
        if d.expires_at and d.expires_at < now:
            return False, "expired"
        dup = (
            await self.s.execute(
                select(GiftCodeRedemption).where(
                    GiftCodeRedemption.code == code,
                    GiftCodeRedemption.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if dup:
            return False, "already_used"
        if d.used_count >= d.usage_limit:
            return False, "exhausted"
        d.used_count += 1
        self.s.add(GiftCodeRedemption(code=code, user_id=user_id))
        await self.add_balance(user_id, d.amount, reason=f"gift:{code}", actor_id=user_id)
        log.info("gift.redeemed", user_id=user_id, code=code, amount=d.amount)
        return True, "ok"

    # ---- payment reports ------------------------------------------------
    async def mark_paid(self, order_id: str, *, credit_user: bool = True) -> PaymentReport | None:
        rep = (
            await self.s.execute(select(PaymentReport).where(PaymentReport.order_id == order_id))
        ).scalar_one_or_none()
        if rep is None or rep.payment_status == "paid":
            return rep  # idempotent - double webhook safe (legacy back.php did the same)
        rep.payment_status = "paid"
        if credit_user and rep.gateway != "purchase":
            await self.add_balance(rep.user_id, rep.price, reason=f"pay:{rep.gateway}")
        await self.s.commit()
        log.info("payment.paid", order_id=order_id, price=rep.price, gateway=rep.gateway)
        return rep

    async def create_topup(self, user_id: int, amount: int, gateway: str, meta: dict[str, Any] | None = None) -> PaymentReport:
        from mirza.payments.base import new_order_id

        rep = PaymentReport(order_id=new_order_id(), user_id=user_id, price=amount,
                            gateway=gateway, meta=meta or {})
        self.s.add(rep)
        await self.s.commit()
        return rep
