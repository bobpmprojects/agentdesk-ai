"""Policy-guarded return, refund, credit, and replacement tools."""

from __future__ import annotations

from typing import cast

from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyCheckInput, PolicyEngine
from agentdesk.schemas.tools import (
    AssessReturnArgs,
    AssessReturnResult,
    CreateRefundArgs,
    CreateRefundResult,
    CreateReplacementArgs,
    CreateReplacementResult,
    CreateReturnLabelArgs,
    CreateReturnLabelResult,
    IssueStoreCreditArgs,
    IssueStoreCreditResult,
)


def _order_and_decision(
    repository: Repository,
    policy: PolicyEngine,
    *,
    identity,
    order_id: str,
    operation: str,
    amount=None,
):
    order = repository.get_order(identity, order_id)
    if order.error:
        raise PermissionError(order.error.message)
    decision = policy.check(
        PolicyCheckInput(
            operation=operation,
            identity_verified=True,
            order_status=order.status,
            order_total=order.total,
            requested_amount=amount,
            delivered_at=order.delivered_at,
        )
    )
    return order, decision


def assess_return(
    repository: Repository,
    policy: PolicyEngine,
    args: AssessReturnArgs,
) -> AssessReturnResult:
    order, decision = _order_and_decision(
        repository,
        policy,
        identity=args.identity,
        order_id=args.order_id,
        operation="return",
    )
    days = (
        (PolicyCheckInput(
            operation="return",
            identity_verified=True,
            order_status=order.status,
            order_total=order.total,
        ).now - order.delivered_at).days
        if order.delivered_at
        else None
    )
    return AssessReturnResult(
        eligible=decision.allowed,
        days_since_delivery=max(days, 0) if days is not None else None,
        refundable_amount=order.total if decision.allowed else None,
        decision=decision,
    )


def create_refund(
    repository: Repository,
    policy: PolicyEngine,
    args: CreateRefundArgs,
) -> CreateRefundResult:
    _, decision = _order_and_decision(
        repository,
        policy,
        identity=args.identity,
        order_id=args.order_id,
        operation="refund",
        amount=args.amount,
    )
    return cast(
        CreateRefundResult,
        repository.create_refund(
            args.identity,
            args.order_id,
            args.item_id,
            args.amount,
            args.idempotency_key,
            decision,
        ),
    )


def issue_store_credit(
    repository: Repository,
    policy: PolicyEngine,
    args: IssueStoreCreditArgs,
) -> IssueStoreCreditResult:
    _, decision = _order_and_decision(
        repository,
        policy,
        identity=args.identity,
        order_id=args.order_id,
        operation="store_credit",
        amount=args.amount,
    )
    return cast(
        IssueStoreCreditResult,
        repository.create_refund(
            args.identity,
            args.order_id,
            "ORDER",
            args.amount,
            args.idempotency_key,
            decision,
            kind="store_credit",
        ),
    )


def create_return_label(
    repository: Repository,
    policy: PolicyEngine,
    args: CreateReturnLabelArgs,
) -> CreateReturnLabelResult:
    _, decision = _order_and_decision(
        repository,
        policy,
        identity=args.identity,
        order_id=args.order_id,
        operation="return",
    )
    return cast(
        CreateReturnLabelResult,
        repository.record_resolution(
            args.identity,
            args.order_id,
            args.item_id,
            args.idempotency_key,
            decision,
            "return_label",
        ),
    )


def create_replacement(
    repository: Repository,
    policy: PolicyEngine,
    args: CreateReplacementArgs,
) -> CreateReplacementResult:
    _, decision = _order_and_decision(
        repository,
        policy,
        identity=args.identity,
        order_id=args.order_id,
        operation="replace",
    )
    return cast(
        CreateReplacementResult,
        repository.record_resolution(
            args.identity,
            args.order_id,
            args.item_id,
            args.idempotency_key,
            decision,
            "replace",
        ),
    )
