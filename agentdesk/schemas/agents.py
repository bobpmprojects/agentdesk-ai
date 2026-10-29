"""Typed agent input and output contracts."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from agentdesk.schemas.common import (
    ActionClaim,
    AgentContext,
    ContractModel,
    Intent,
    Money,
    OrderStatus,
    PolicyDecision,
    VerifiedIdentity,
)


class PlanStep(ContractModel):
    step_id: str
    intent: Intent
    specialist: Literal[
        "identity", "orders", "returns_refunds", "account", "policy_knowledge"
    ]
    depends_on: list[str] = Field(default_factory=list)
    requested_operation: str


class SupervisorInput(ContractModel):
    context: AgentContext
    order_id: str
    email: SecretStr


class SupervisorOutput(ContractModel):
    intents: list[Intent] = Field(min_length=1, max_length=3)
    plan: list[PlanStep] = Field(min_length=1)
    final_reply: str


class IdentityAgentInput(ContractModel):
    context: AgentContext
    order_id: str
    email: SecretStr


class IdentityAgentOutput(ContractModel):
    verified: bool
    identity: VerifiedIdentity | None = None
    failure_reason: Literal["missing_credentials", "no_match", "locked"] | None = None


class OrdersAgentInput(ContractModel):
    context: AgentContext
    task: Literal["status", "tracking", "cancel"]
    idempotency_key: UUID | None = None


class OrdersAgentOutput(ContractModel):
    order_id: str
    status: OrderStatus
    ordered_total: Money
    carrier: str | None = None
    tracking_number_redacted: str | None = None
    estimated_delivery: date | None = None
    policy_decision: PolicyDecision | None = None
    action: ActionClaim | None = None


class ReturnsRefundsAgentInput(ContractModel):
    context: AgentContext
    task: Literal[
        "assess_return", "create_return_label", "refund", "store_credit", "replace"
    ]
    item_id: str
    reason: Literal["damaged", "wrong_item", "other"]
    idempotency_key: UUID | None = None


class ReturnsRefundsAgentOutput(ContractModel):
    eligible: bool
    resolution: Literal[
        "return_label", "refund", "store_credit", "replacement", "denied"
    ]
    amount: Money | None = None
    policy_decision: PolicyDecision
    action: ActionClaim | None = None
    explanation: str


class RefundSupervisorInput(ContractModel):
    context: AgentContext
    order_id: str
    email: SecretStr
    item_id: str
    reason: Literal["damaged", "wrong_item", "other"] = "damaged"
    idempotency_key: UUID


class RefundSupervisorOutput(ContractModel):
    plan: list[PlanStep] = Field(min_length=1)
    final_reply: str
    resolution: ReturnsRefundsAgentOutput | None = None
