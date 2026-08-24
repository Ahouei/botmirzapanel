"""Referral / affiliate service. (Legacy affiliates table + index.php ref logic.)"""
from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mirza.db.models import BotSetting, Referral, User

log = structlog.get_logger(__name__)


class ReferralService:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def resolve(self, code: str) -> User | None:
        return (
            await self.s.execute(select(User).where(User.ref_code == code))
        ).scalar_one_or_none()

    async def bind(self, referred_id: int, referrer: User) -> bool:
        """One-time binding; self-ref and mutual loops rejected."""
        if referred_id == referrer.id:
            return False
        existing = (
            await self.s.execute(
                select(Referral).where(Referral.referred_id == referred_id)
            )
        ).scalar_one_or_none()
        if existing:
            return False
        self.s.add(Referral(referrer_id=referrer.id, referred_id=referred_id))
        await self.s.execute(
            User.__table__.update().where(User.id == referrer.id)
            .values(referral_count=User.referral_count + 1)
        )
        # legacy mutual-block: a user who was referred BY you can't be your referrer
        await self.s.commit()
        log.info("referral.bound", referrer=referrer.id, referred=referred_id)
        return True

    async def reward_amount(self) -> int:
        v = (
            await self.s.execute(
                select(BotSetting.value).where(BotSetting.key == "referral_reward")
            )
        ).scalar_one_or_none()
        return int(v or 0)

    async def stats_for(self, user_id: int) -> dict:
        cnt = (
            await self.s.execute(
                select(func.count()).select_from(Referral).where(Referral.referrer_id == user_id)
            )
        ).scalar()
        return {"count": cnt or 0, "reward": await self.reward_amount()}
