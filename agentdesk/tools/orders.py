"""Read-only order tools."""

from agentdesk.db.repository import Repository
from agentdesk.schemas.tools import (
    GetOrderArgs,
    GetOrderResult,
    GetTrackingArgs,
    GetTrackingResult,
)


def get_order(repository: Repository, args: GetOrderArgs) -> GetOrderResult:
    return repository.get_order(args.identity, args.order_id)


def get_tracking(repository: Repository, args: GetTrackingArgs) -> GetTrackingResult:
    return repository.get_tracking(args.identity, args.order_id)
