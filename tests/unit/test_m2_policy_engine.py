from datetime import UTC, datetime, timedelta
from decimal import Decimal

from agentdesk.policy.engine import PolicyCheckInput, PolicyEngine
from agentdesk.schemas.common import Money


def refund_decision(amount: str):
    now = datetime(2026, 10, 29, tzinfo=UTC)
    return PolicyEngine().check(
        PolicyCheckInput(
            operation="refund",
            identity_verified=True,
            order_status="delivered-damaged",
            order_total=Money(amount=Decimal(amount)),
            requested_amount=Money(amount=Decimal(amount)),
            delivered_at=now - timedelta(days=30),
            now=now,
        )
    )


def test_refund_boundary_is_inclusive_at_200() -> None:
    assert refund_decision("200.00").allowed is True


def test_refund_above_200_offers_store_credit() -> None:
    decision = refund_decision("200.01")
    assert decision.allowed is False
    assert decision.alternative == "Offer store credit."


def test_identity_is_required_before_other_policy_rules() -> None:
    decision = PolicyEngine().check(
        PolicyCheckInput(
            operation="cancel",
            identity_verified=False,
            order_status="processing",
            order_total=Money(amount=Decimal("10")),
        )
    )
    assert decision.allowed is False
    assert decision.rule_id == "identity-required"
