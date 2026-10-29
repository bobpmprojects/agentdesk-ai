"""Typed agent input and output contracts."""

from datetime import date
from typing import Literal

from pydantic import Field, SecretStr

from agentdesk.schemas.common import (
    AgentContext,
    ContractModel,
    Intent,
    Money,
    OrderStatus,
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
    task: Literal["status", "tracking"]


class OrdersAgentOutput(ContractModel):
    order_id: str
    status: OrderStatus
    ordered_total: Money
    carrier: str | None = None
    tracking_number_redacted: str | None = None
    estimated_delivery: date | None = None
