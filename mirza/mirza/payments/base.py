"""Payment gateway contract + shared helpers.

A gateway = create payment (return pay URL) + verify webhook/callback.
"""
from __future__ import annotations

import abc
import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass
class PaymentRequest:
    order_id: str
    user_id: int
    amount: Decimal            # in gateway currency units (IRR, USD...)
    description: str = ""
    meta: dict[str, Any] | None = None


@dataclass
class PaymentResult:
    ok: bool
    pay_url: str | None = None
    gateway_ref: str | None = None
    message: str | None = None


class BaseGateway(abc.ABC):
    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abc.abstractmethod
    async def create_payment(self, req: PaymentRequest) -> PaymentResult:
        """Initiate; return URL to show the user as an inline button."""

    @abc.abstractmethod
    async def verify_callback(self, payload: dict[str, Any]) -> tuple[str, bool]:
        """Validate callback/webhook body.
        Returns (order_id, success). Must re-verify with the API server-side."""


def new_order_id() -> str:
    return "mirza" + secrets.token_hex(8)
