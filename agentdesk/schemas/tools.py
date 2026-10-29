"""Typed tool argument and result contracts."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from agentdesk.schemas.common import (
    ContractModel,
    Money,
    OrderStatus,
    PolicyDecision,
    VerifiedIdentity,
)


class ToolError(ContractModel):
    code: Literal[
        "identity_required",
        "not_found",
        "policy_denied",
        "invalid_state",
        "idempotency_conflict",
        "validation_error",
    ]
    message: str
    retryable: bool = False


class AuditRecord(ContractModel):
    audit_id: UUID
    idempotency_key: UUID
    operation: str
    outcome: Literal["committed", "denied", "duplicate", "failed"]
    policy_decision_id: UUID | None = None
    created_at: datetime


class VerifyIdentityArgs(ContractModel):
    order_id: str
    email: SecretStr


class VerifyIdentityResult(ContractModel):
    verified: bool
    identity: VerifiedIdentity | None = None
    error: ToolError | None = None


class GetOrderArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str


class GetOrderResult(ContractModel):
    order_id: str
    status: OrderStatus
    ordered_at: datetime
    delivered_at: datetime | None = None
    total: Money
    error: ToolError | None = None


class GetTrackingArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str


class GetTrackingResult(ContractModel):
    status: OrderStatus
    carrier: str | None = None
    tracking_number_redacted: str | None = None
    estimated_delivery: date | None = None
    error: ToolError | None = None


class CancelOrderArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    idempotency_key: UUID


class CancelOrderResult(ContractModel):
    cancelled: bool
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class AssessReturnArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    reason: Literal["damaged", "wrong_item", "other"]


class AssessReturnResult(ContractModel):
    eligible: bool
    days_since_delivery: int | None = Field(default=None, ge=0)
    refundable_amount: Money | None = None
    decision: PolicyDecision
    error: ToolError | None = None


class CreateReturnLabelArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    idempotency_key: UUID


class CreateReturnLabelResult(ContractModel):
    label_id: UUID | None = None
    label_reference: str | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class CreateRefundArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    amount: Money
    idempotency_key: UUID


class CreateRefundResult(ContractModel):
    refund_id: UUID | None = None
    amount: Money | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class IssueStoreCreditArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    amount: Money
    idempotency_key: UUID


class IssueStoreCreditResult(ContractModel):
    credit_id: UUID | None = None
    amount: Money | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class CreateReplacementArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    item_id: str
    idempotency_key: UUID


class CreateReplacementResult(ContractModel):
    replacement_order_id: str | None = None
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class AddressInput(ContractModel):
    line1: str
    line2: str | None = None
    city: str
    region: str
    postal_code: str
    country_code: str = Field(min_length=2, max_length=2)


class ChangeShippingAddressArgs(ContractModel):
    identity: VerifiedIdentity
    order_id: str
    address: AddressInput
    idempotency_key: UUID
    replacement_context: bool = False


class ChangeShippingAddressResult(ContractModel):
    address_id: UUID | None = None
    change_count: int = Field(ge=0, le=1)
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None


class UpdateContactPreferencesArgs(ContractModel):
    identity: VerifiedIdentity
    email_opt_in: bool | None = None
    sms_opt_in: bool | None = None
    idempotency_key: UUID


class UpdateContactPreferencesResult(ContractModel):
    updated: bool
    decision: PolicyDecision
    audit: AuditRecord
    error: ToolError | None = None
