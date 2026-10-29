"""Read-only Orders specialist."""

from agentdesk.db.repository import Repository
from agentdesk.schemas.agents import OrdersAgentInput, OrdersAgentOutput
from agentdesk.schemas.tools import GetOrderArgs, GetTrackingArgs
from agentdesk.tools.orders import get_order, get_tracking


class OrdersAgent:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

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
