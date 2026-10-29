"""Plain-Python policy rules. No model can override these decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from agentdesk.schemas.common import (
    ContractModel,
    Money,
    OrderStatus,
    PolicyDecision,
)


class PolicyCheckInput(ContractModel):
    operation: Literal[
        "cancel", "return", "refund", "store_credit", "replace"
    ]
    identity_verified: bool
    order_status: OrderStatus
    order_total: Money
    requested_amount: Money | None = None
    delivered_at: datetime | None = None
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PolicyEngine:
    def _decision(
        self,
        check: PolicyCheckInput,
        *,
        allowed: bool,
        rule_id: str,
        reason: str,
        alternative: str | None = None,
    ) -> PolicyDecision:
        signature = (
            f"{check.operation}:{check.order_status}:{check.order_total.amount}:"
            f"{check.requested_amount.amount if check.requested_amount else ''}:"
            f"{check.delivered_at}:{allowed}:{rule_id}"
        )
        return PolicyDecision(
            decision_id=uuid5(NAMESPACE_URL, f"agentdesk-policy:{signature}"),
            operation=check.operation,
            allowed=allowed,
            rule_id=rule_id,
            reason=reason,
            alternative=alternative,
        )

    def check(self, check: PolicyCheckInput) -> PolicyDecision:
        if not check.identity_verified:
            return self._decision(
                check,
                allowed=False,
                rule_id="identity-required",
                reason="Identity verification is required for all writes.",
            )

        if check.operation == "cancel":
            allowed = check.order_status == OrderStatus.PROCESSING
            return self._decision(
                check,
                allowed=allowed,
                rule_id="cancel-before-shipment",
                reason=(
                    "The order has not shipped and may be cancelled."
                    if allowed
                    else "The order has already shipped or completed."
                ),
                alternative=None if allowed else "Request a return after delivery.",
            )

        if check.delivered_at is None:
            return self._decision(
                check,
                allowed=False,
                rule_id="delivery-required",
                reason="This resolution requires a delivered order.",
            )
        now = check.now
        delivered_at = check.delivered_at
        if delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        days = (now - delivered_at).days
        if days < 0 or days > 30:
            return self._decision(
                check,
                allowed=False,
                rule_id="return-window-30-days",
                reason="The order is outside the 30-day delivery window.",
                alternative="Create a support ticket for manual review.",
            )

        if check.operation == "refund":
            amount = check.requested_amount or check.order_total
            if amount.amount > 200:
                return self._decision(
                    check,
                    allowed=False,
                    rule_id="refund-cap-200",
                    reason="Cash refunds above $200 are not automatically approved.",
                    alternative="Offer store credit.",
                )
            return self._decision(
                check,
                allowed=True,
                rule_id="refund-within-cap-and-window",
                reason="The refund is within $200 and 30 days of delivery.",
            )

        return self._decision(
            check,
            allowed=True,
            rule_id=f"{check.operation}-within-window",
            reason="The verified request is within 30 days of delivery.",
        )
