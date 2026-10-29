"""Policy-guarded account write tools."""

from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyCheckInput, PolicyEngine
from agentdesk.schemas.tools import (
    ChangeShippingAddressArgs,
    ChangeShippingAddressResult,
    UpdateContactPreferencesArgs,
    UpdateContactPreferencesResult,
)


def change_shipping_address(
    repository: Repository,
    policy: PolicyEngine,
    args: ChangeShippingAddressArgs,
) -> ChangeShippingAddressResult:
    order = repository.get_order(args.identity, args.order_id)
    if order.error:
        raise PermissionError(order.error.message)
    count = repository.address_change_count(args.identity, args.order_id)
    decision = policy.check(
        PolicyCheckInput(
            operation="change_shipping_address",
            identity_verified=True,
            order_status=order.status,
            order_total=order.total,
            delivered_at=order.delivered_at,
            address_change_count=count,
            replacement_context=args.replacement_context,
        )
    )
    return repository.change_shipping_address(
        args.identity,
        args.order_id,
        args.address,
        args.idempotency_key,
        decision,
    )


def update_contact_preferences(
    repository: Repository,
    policy: PolicyEngine,
    args: UpdateContactPreferencesArgs,
) -> UpdateContactPreferencesResult:
    order = repository.get_order(args.identity, args.identity.order_id)
    if order.error:
        raise PermissionError(order.error.message)
    decision = policy.check(
        PolicyCheckInput(
            operation="update_contact_preferences",
            identity_verified=True,
            order_status=order.status,
            order_total=order.total,
            delivered_at=order.delivered_at,
        )
    )
    return repository.update_contact_preferences(
        args.identity,
        args.email_opt_in,
        args.sms_opt_in,
        args.idempotency_key,
        decision,
    )
