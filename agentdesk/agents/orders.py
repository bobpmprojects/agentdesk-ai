"""Read-only Orders specialist."""

from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyEngine
from agentdesk.schemas.agents import OrdersAgentInput, OrdersAgentOutput
from agentdesk.schemas.common import ActionClaim
from agentdesk.schemas.tools import CancelOrderArgs, GetOrderArgs, GetTrackingArgs
from agentdesk.tools.orders import cancel_order, get_order, get_tracking


class OrdersAgent:
    def __init__(
        self, repository: Repository, policy: PolicyEngine | None = None
    ) -> None:
        self.repository = repository
        self.policy = policy or PolicyEngine()

    def run(self, request: OrdersAgentInput) -> OrdersAgentOutput:
        identity = request.context.identity
        if identity is None:
            raise PermissionError("Identity verification is required before order lookup")

        order = get_order(
            self.repository,
            GetOrderArgs(identity=identity, order_id=identity.order_id),
        )
        if order.error:
            raise PermissionError(order.error.message)

        if request.task == "cancel":
            if request.idempotency_key is None:
                raise ValueError("Cancellation requires an idempotency key")
            result = cancel_order(
                self.repository,
                self.policy,
                CancelOrderArgs(
                    identity=identity,
                    order_id=identity.order_id,
                    idempotency_key=request.idempotency_key,
                ),
            )
            return OrdersAgentOutput(
                order_id=order.order_id,
                status="cancelled" if result.cancelled else order.status,
                ordered_total=order.total,
                policy_decision=result.decision,
                action=(
                    ActionClaim(
                        action_type="cancel",
                        audit_id=result.audit.audit_id,
                        order_id=order.order_id,
                        description="Order cancelled.",
                    )
                    if result.cancelled
                    else None
                ),
            )

        tracking = get_tracking(
            self.repository,
            GetTrackingArgs(identity=identity, order_id=identity.order_id),
        )
        return OrdersAgentOutput(
            order_id=order.order_id,
            status=order.status,
            ordered_total=order.total,
            carrier=tracking.carrier,
            tracking_number_redacted=tracking.tracking_number_redacted,
            estimated_delivery=tracking.estimated_delivery,
        )
