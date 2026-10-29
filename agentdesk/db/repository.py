"""Typed persistence operations; no agent accesses SQLite directly."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from agentdesk.schemas.common import Money, VerifiedIdentity
from agentdesk.schemas.tools import (
    GetOrderResult,
    GetTrackingResult,
    ToolError,
    VerifyIdentityResult,
)


class Repository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def verify_identity(self, order_id: str, email: str) -> VerifyIdentityResult:
        row = self.connection.execute(
            """
            SELECT orders.id AS order_id, customers.id AS customer_id
            FROM orders
            JOIN customers ON customers.id = orders.customer_id
            WHERE orders.id = ? AND lower(customers.email) = lower(?)
            """,
            (order_id, email),
        ).fetchone()
        if row is None:
            return VerifyIdentityResult(
                verified=False,
                error=ToolError(
                    code="not_found",
                    message="The order ID and email did not match.",
                ),
            )
        return VerifyIdentityResult(
            verified=True,
            identity=VerifiedIdentity(
                customer_id=row["customer_id"],
                order_id=row["order_id"],
                verified_at=datetime.now().astimezone(),
                verification_id=uuid4(),
            ),
        )

    def _identity_matches(self, identity: VerifiedIdentity, order_id: str) -> bool:
        if identity.order_id != order_id:
            return False
        row = self.connection.execute(
            "SELECT customer_id FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        return row is not None and row["customer_id"] == str(identity.customer_id)

    def get_order(
        self, identity: VerifiedIdentity, order_id: str
    ) -> GetOrderResult:
        if not self._identity_matches(identity, order_id):
            return GetOrderResult(
                order_id=order_id,
                status="processing",
                ordered_at=identity.verified_at,
                total=Money(amount=Decimal("0")),
                error=ToolError(
                    code="identity_required",
                    message="Identity verification is required for this order.",
                ),
            )
        row = self.connection.execute(
            """
            SELECT id, status, ordered_at, delivered_at, total_cents
            FROM orders WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return GetOrderResult(
                order_id=order_id,
                status="processing",
                ordered_at=identity.verified_at,
                total=Money(amount=Decimal("0")),
                error=ToolError(code="not_found", message="Order not found."),
            )
        return GetOrderResult(
            order_id=row["id"],
            status=row["status"],
            ordered_at=datetime.fromisoformat(row["ordered_at"]),
            delivered_at=(
                datetime.fromisoformat(row["delivered_at"])
                if row["delivered_at"]
                else None
            ),
            total=Money(amount=Decimal(row["total_cents"]) / 100),
        )

    def get_tracking(
        self, identity: VerifiedIdentity, order_id: str
    ) -> GetTrackingResult:
        if not self._identity_matches(identity, order_id):
            return GetTrackingResult(
                status="processing",
                error=ToolError(
                    code="identity_required",
                    message="Identity verification is required for this order.",
                ),
            )
        row = self.connection.execute(
            """
            SELECT orders.status, shipments.carrier, shipments.tracking_number,
                   shipments.estimated_delivery
            FROM orders
            LEFT JOIN shipments ON shipments.order_id = orders.id
            WHERE orders.id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            return GetTrackingResult(
                status="processing",
                error=ToolError(code="not_found", message="Order not found."),
            )
        tracking = row["tracking_number"]
        return GetTrackingResult(
            status=row["status"],
            carrier=row["carrier"],
            tracking_number_redacted=f"••••{tracking[-4:]}" if tracking else None,
            estimated_delivery=(
                date.fromisoformat(row["estimated_delivery"])
                if row["estimated_delivery"]
                else None
            ),
        )
