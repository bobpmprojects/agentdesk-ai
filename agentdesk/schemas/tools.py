"""Typed tool argument and result contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import SecretStr

from agentdesk.schemas.common import (
    ContractModel,
    Money,
    OrderStatus,
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
