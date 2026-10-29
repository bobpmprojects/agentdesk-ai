"""Returns & Refunds specialist with deterministic policy authorization."""

from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyEngine
from agentdesk.schemas.agents import (
    ReturnsRefundsAgentInput,
    ReturnsRefundsAgentOutput,
)
from agentdesk.schemas.common import ActionClaim
from agentdesk.schemas.tools import (
    AssessReturnArgs,
    CreateRefundArgs,
    CreateReplacementArgs,
    CreateReturnLabelArgs,
    IssueStoreCreditArgs,
)
from agentdesk.tools.returns_refunds import (
    assess_return,
    create_refund,
    create_replacement,
    create_return_label,
    issue_store_credit,
)


class ReturnsRefundsAgent:
    def __init__(
        self, repository: Repository, policy: PolicyEngine | None = None
    ) -> None:
        self.repository = repository
        self.policy = policy or PolicyEngine()

    def run(self, request: ReturnsRefundsAgentInput) -> ReturnsRefundsAgentOutput:
        identity = request.context.identity
        if identity is None:
            raise PermissionError("Identity verification is required before any write")
        order = self.repository.get_order(identity, identity.order_id)
        if order.error:
            raise PermissionError(order.error.message)

        if request.task == "assess_return":
            result = assess_return(
                self.repository,
                self.policy,
                AssessReturnArgs(
                    identity=identity,
                    order_id=identity.order_id,
                    item_id=request.item_id,
                    reason=request.reason,
                ),
            )
            return ReturnsRefundsAgentOutput(
                eligible=result.eligible,
                resolution="refund" if result.eligible else "denied",
                amount=result.refundable_amount,
                policy_decision=result.decision,
                explanation=result.decision.reason,
            )

        if request.idempotency_key is None:
            raise ValueError("Write resolutions require an idempotency key")

        if request.task == "refund":
            result = create_refund(
                self.repository,
                self.policy,
                CreateRefundArgs(
                    identity=identity,
                    order_id=identity.order_id,
                    item_id=request.item_id,
                    amount=order.total,
                    idempotency_key=request.idempotency_key,
                ),
            )
            return ReturnsRefundsAgentOutput(
                eligible=result.decision.allowed,
                resolution="refund" if result.decision.allowed else "denied",
                amount=result.amount,
                policy_decision=result.decision,
                action=(
                    ActionClaim(
                        action_type="refund",
                        audit_id=result.audit.audit_id,
                        order_id=identity.order_id,
                        description=f"Refunded ${order.total.amount}.",
                    )
                    if result.decision.allowed
                    else None
                ),
                explanation=(
                    result.decision.reason
                    if result.decision.allowed
                    else (
                        f"{result.decision.reason} "
                        f"{result.decision.alternative or ''}"
                    ).strip()
                ),
            )

        if request.task == "store_credit":
            result = issue_store_credit(
                self.repository,
                self.policy,
                IssueStoreCreditArgs(
                    identity=identity,
                    order_id=identity.order_id,
                    amount=order.total,
                    idempotency_key=request.idempotency_key,
                ),
            )
            action_type = "store_credit"
            resolution = "store_credit"
            amount = result.amount
        elif request.task == "create_return_label":
            result = create_return_label(
                self.repository,
                self.policy,
                CreateReturnLabelArgs(
                    identity=identity,
                    order_id=identity.order_id,
                    item_id=request.item_id,
                    idempotency_key=request.idempotency_key,
                ),
            )
            action_type = "return_label"
            resolution = "return_label"
            amount = None
        else:
            result = create_replacement(
                self.repository,
                self.policy,
                CreateReplacementArgs(
                    identity=identity,
                    order_id=identity.order_id,
                    item_id=request.item_id,
                    idempotency_key=request.idempotency_key,
                ),
            )
            action_type = "replacement"
            resolution = "replacement"
            amount = None

        return ReturnsRefundsAgentOutput(
            eligible=result.decision.allowed,
            resolution=resolution if result.decision.allowed else "denied",
            amount=amount,
            policy_decision=result.decision,
            action=(
                ActionClaim(
                    action_type=action_type,
                    audit_id=result.audit.audit_id,
                    order_id=identity.order_id,
                    description=f"{action_type.replace('_', ' ').title()} created.",
                )
                if result.decision.allowed
                else None
            ),
            explanation=result.decision.reason,
        )
