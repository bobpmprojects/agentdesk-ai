"""Typed agent input and output contracts."""

from datetime import date, datetime
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
    PolicyCitation,
    PolicyDecision,
    VerifiedIdentity,
)
from agentdesk.schemas.tools import AddressInput


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


class AccountAgentInput(ContractModel):
    context: AgentContext
    task: Literal["change_shipping_address", "update_contact_preferences"]
    new_address: AddressInput | None = None
    email_opt_in: bool | None = None
    sms_opt_in: bool | None = None
    idempotency_key: UUID
    replacement_context: bool = False


class AccountAgentOutput(ContractModel):
    changed: bool
    policy_decision: PolicyDecision
    action: ActionClaim | None = None
    explanation: str


class MultiIntentSupervisorInput(ContractModel):
    context: AgentContext
    order_id: str
    email: SecretStr
    item_id: str
    new_address: AddressInput
    refund_idempotency_key: UUID
    address_idempotency_key: UUID
    replacement_idempotency_key: UUID


class MultiIntentSupervisorOutput(ContractModel):
    intents: list[Intent] = Field(min_length=2, max_length=3)
    plan: list[PlanStep] = Field(min_length=3)
    final_reply: str
    actions: list[ActionClaim] = Field(default_factory=list)


class PolicyKnowledgeAgentInput(ContractModel):
    context: AgentContext
    question: str = Field(min_length=1)
    max_sections: int = Field(default=5, ge=1, le=10)


class PolicyKnowledgeAgentOutput(ContractModel):
    answer: str
    citations: list[PolicyCitation]
    grounded: bool
    insufficient_policy: bool


class DeterministicVerification(ContractModel):
    action_claims_valid: bool
    citations_valid: bool
    errors: list[str] = Field(default_factory=list)


class LLMReplyCheck(ContractModel):
    tone_ok: bool
    unsupported_promises: list[str] = Field(default_factory=list)


class VerifierInput(ContractModel):
    context: AgentContext
    draft_reply: str
    action_claims: list[ActionClaim] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)
    regeneration_count: int = Field(default=0, ge=0, le=1)


class VerifierOutput(ContractModel):
    approved: bool
    deterministic: DeterministicVerification
    llm_check: LLMReplyCheck | None = None
    regenerate: bool
    safe_fallback: str | None = None


class PolicySupervisorInput(ContractModel):
    context: AgentContext


class PolicySupervisorOutput(ContractModel):
    final_reply: str
    citations: list[PolicyCitation] = Field(default_factory=list)
    grounded: bool
    verifier: VerifierOutput


class ConversationState(ContractModel):
    conversation_id: UUID
    identity: VerifiedIdentity | None = None
    active_order_id: str | None = None
    resolved_intents: list[Intent] = Field(default_factory=list)
    pending_intents: list[Intent] = Field(default_factory=list)
    offered_alternatives: list[str] = Field(default_factory=list)
    prior_actions: list[ActionClaim] = Field(default_factory=list)
    idempotency_keys: dict[str, UUID] = Field(default_factory=dict)
    updated_at: datetime


class StartResolutionInput(ContractModel):
    context: AgentContext
    order_id: str
    email: SecretStr
    item_id: str
    preferred_resolution: Literal["replacement", "refund", "store_credit"]
    idempotency_keys: dict[str, UUID]


class ConversationTurnOutput(ContractModel):
    final_reply: str
    state: ConversationState
    actions: list[ActionClaim] = Field(default_factory=list)


class ContinueConversationInput(ContractModel):
    context: AgentContext
    item_id: str
