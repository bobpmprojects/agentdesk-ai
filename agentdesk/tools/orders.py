"""Read-only order tools."""

from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyCheckInput, PolicyEngine
from agentdesk.schemas.tools import (
    CancelOrderArgs,
    CancelOrderResult,
    GetOrderArgs,
    GetOrderResult,
    GetTrackingArgs,
    GetTrackingResult,
)


def get_order(repository: Repository, args: GetOrderArgs) -> GetOrderResult:
    return repository.get_order(args.identity, args.order_id)


def get_tracking(repository: Repository, args: GetTrackingArgs) -> GetTrackingResult:
    return repository.get_tracking(args.identity, args.order_id)


def cancel_order(
    repository: Repository,
    policy: PolicyEngine,
    args: CancelOrderArgs,
) -> CancelOrderResult:
    order = repository.get_order(args.identity, args.order_id)
    if order.error:
        raise PermissionError(order.error.message)
    decision = policy.check(
        PolicyCheckInput(
            operation="cancel",
            identity_verified=True,
            order_status=order.status,
            order_total=order.total,
            delivered_at=order.delivered_at,
        )
    )
    return repository.cancel_order(
        args.identity,
        args.order_id,
        args.idempotency_key,
        decision,
    )
