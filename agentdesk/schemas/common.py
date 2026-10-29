"""Shared Pydantic contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class Intent(StrEnum):
    ORDER_STATUS = "order_status"
    TRACKING = "tracking"
    CANCEL = "cancel"
    RETURN = "return"
    REFUND = "refund"
    STORE_CREDIT = "store_credit"
    REPLACEMENT = "replacement"
    ADDRESS_CHANGE = "address_change"
    CONTACT_PREFERENCES = "contact_preferences"
    POLICY_QUESTION = "policy_question"


class OrderStatus(StrEnum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    DELIVERED_DAMAGED = "delivered-damaged"
    CANCELLED = "cancelled"


class Money(ContractModel):
    amount: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    currency: Literal["USD"] = "USD"


class VerifiedIdentity(ContractModel):
    customer_id: UUID
    order_id: str
    verified_at: datetime
    verification_id: UUID


class AgentContext(ContractModel):
    conversation_id: UUID
    turn_id: UUID
    customer_message: str = Field(min_length=1)
    identity: VerifiedIdentity | None = None
    active_order_id: str | None = None


class ActionClaim(ContractModel):
    action_type: str
    audit_id: UUID
    order_id: str | None = None
    description: str


class PolicyCitation(ContractModel):
    document: str
    section_id: str
    section_title: str
    quote: str = Field(min_length=1)


class PolicyDecision(ContractModel):
    decision_id: UUID
    operation: str
    allowed: bool
    rule_id: str
    reason: str
    alternative: str | None = None


class TraceEvent(ContractModel):
    event_id: UUID
    conversation_id: UUID
    turn_id: UUID
    timestamp: datetime
    event_type: Literal[
        "agent_start",
        "agent_end",
        "tool_start",
        "tool_end",
        "policy_decision",
        "verification",
        "model_call",
    ]
    agent: str
    tool: str | None = None
    args_redacted: dict[str, Any] = Field(default_factory=dict)
    policy_decision: PolicyDecision | None = None
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
