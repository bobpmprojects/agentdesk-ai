"""Typed persistence operations; no agent accesses SQLite directly."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from agentdesk.schemas.common import Money, PolicyDecision, VerifiedIdentity
from agentdesk.schemas.tools import (
    AddressInput,
    AuditRecord,
    CancelOrderResult,
    ChangeShippingAddressResult,
    CreateRefundResult,
    CreateReplacementResult,
    CreateReturnLabelResult,
    GetOrderResult,
    GetTrackingResult,
    IssueStoreCreditResult,
    LookupAuditActionsResult,
    ToolError,
    UpdateContactPreferencesResult,
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
                total=Money(amount=Decimal(0)),
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
                total=Money(amount=Decimal(0)),
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

    def get_order_item(self, identity: VerifiedIdentity, order_id: str) -> str | None:
        """Return the order's item ID, only for a verified identity on that order."""
        if not self._identity_matches(identity, order_id):
            return None
        row = self.connection.execute(
            "SELECT item_id FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return row["item_id"] if row is not None else None

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

    def _audit_record(self, row: sqlite3.Row) -> AuditRecord:
        return AuditRecord(
            audit_id=row["id"],
            idempotency_key=row["idempotency_key"],
            operation=row["operation"],
            outcome=row["outcome"],
            policy_decision_id=row["policy_decision_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _existing_audit(self, idempotency_key: UUID) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM audit_log WHERE idempotency_key = ?",
            (str(idempotency_key),),
        ).fetchone()

    def _insert_audit(
        self,
        *,
        order_id: str,
        idempotency_key: UUID,
        operation: str,
        outcome: str,
        decision: PolicyDecision,
        details: dict[str, object],
    ) -> AuditRecord:
        audit_id = uuid4()
        created_at = datetime.now().astimezone()
        self.connection.execute(
            """
            INSERT INTO audit_log (
                id, order_id, idempotency_key, operation, outcome,
                policy_decision_id, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(audit_id),
                order_id,
                str(idempotency_key),
                operation,
                outcome,
                str(decision.decision_id),
                json.dumps(details, sort_keys=True),
                created_at.isoformat(),
            ),
        )
        return AuditRecord(
            audit_id=audit_id,
            idempotency_key=idempotency_key,
            operation=operation,
            outcome=outcome,
            policy_decision_id=decision.decision_id,
            created_at=created_at,
        )

    def cancel_order(
        self,
        identity: VerifiedIdentity,
        order_id: str,
        idempotency_key: UUID,
        decision: PolicyDecision,
    ) -> CancelOrderResult:
        if not self._identity_matches(identity, order_id):
            raise PermissionError("Identity verification is required for this order")
        existing = self._existing_audit(idempotency_key)
        if existing:
            return CancelOrderResult(
                cancelled=existing["outcome"] == "committed",
                decision=decision,
                audit=self._audit_record(existing),
            )
        with self.connection:
            if decision.allowed:
                self.connection.execute(
                    "UPDATE orders SET status = 'cancelled' WHERE id = ?",
                    (order_id,),
                )
            audit = self._insert_audit(
                order_id=order_id,
                idempotency_key=idempotency_key,
                operation="cancel",
                outcome="committed" if decision.allowed else "denied",
                decision=decision,
                details={"cancelled": decision.allowed},
            )
        return CancelOrderResult(
            cancelled=decision.allowed,
            decision=decision,
            audit=audit,
            error=(
                None
                if decision.allowed
                else ToolError(code="policy_denied", message=decision.reason)
            ),
        )

    def create_refund(
        self,
        identity: VerifiedIdentity,
        order_id: str,
        item_id: str,
        amount: Money,
        idempotency_key: UUID,
        decision: PolicyDecision,
        *,
        kind: str = "cash",
    ) -> CreateRefundResult | IssueStoreCreditResult:
        if not self._identity_matches(identity, order_id):
            raise PermissionError("Identity verification is required for this order")
        existing = self._existing_audit(idempotency_key)
        if existing:
            details = json.loads(existing["details_json"])
            result_type = (
                IssueStoreCreditResult if kind == "store_credit" else CreateRefundResult
            )
            identifier_field = (
                {"credit_id": details.get("refund_id")}
                if kind == "store_credit"
                else {"refund_id": details.get("refund_id")}
            )
            return result_type(
                **identifier_field,
                amount=amount if existing["outcome"] == "committed" else None,
                decision=decision,
                audit=self._audit_record(existing),
                error=(
                    None
                    if existing["outcome"] == "committed"
                    else ToolError(code="policy_denied", message=decision.reason)
                ),
            )

        refund_id = uuid4() if decision.allowed else None
        operation = "store_credit" if kind == "store_credit" else "refund"
        with self.connection:
            if refund_id:
                self.connection.execute(
                    """
                    INSERT INTO refunds (
                        id, order_id, item_id, amount_cents, kind, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(refund_id),
                        order_id,
                        item_id,
                        int(amount.amount * 100),
                        kind,
                        datetime.now().astimezone().isoformat(),
                    ),
                )
            audit = self._insert_audit(
                order_id=order_id,
                idempotency_key=idempotency_key,
                operation=operation,
                outcome="committed" if decision.allowed else "denied",
                decision=decision,
                details={
                    "refund_id": str(refund_id) if refund_id else None,
                    "amount": str(amount.amount),
                    "kind": kind,
                },
            )

        error = (
            None
            if decision.allowed
            else ToolError(code="policy_denied", message=decision.reason)
        )
        if kind == "store_credit":
            return IssueStoreCreditResult(
                credit_id=refund_id,
                amount=amount if decision.allowed else None,
                decision=decision,
                audit=audit,
                error=error,
            )
        return CreateRefundResult(
            refund_id=refund_id,
            amount=amount if decision.allowed else None,
            decision=decision,
            audit=audit,
            error=error,
        )

    def record_resolution(
        self,
        identity: VerifiedIdentity,
        order_id: str,
        item_id: str,
        idempotency_key: UUID,
        decision: PolicyDecision,
        operation: str,
    ) -> CreateReturnLabelResult | CreateReplacementResult:
        if not self._identity_matches(identity, order_id):
            raise PermissionError("Identity verification is required for this order")
        existing = self._existing_audit(idempotency_key)
        if existing:
            details = json.loads(existing["details_json"])
            audit = self._audit_record(existing)
        else:
            reference_id = uuid4() if decision.allowed else None
            details = {"reference_id": str(reference_id) if reference_id else None}
            with self.connection:
                audit = self._insert_audit(
                    order_id=order_id,
                    idempotency_key=idempotency_key,
                    operation=operation,
                    outcome="committed" if decision.allowed else "denied",
                    decision=decision,
                    details=details,
                )
        error = (
            None
            if decision.allowed
            else ToolError(code="policy_denied", message=decision.reason)
        )
        if operation == "return_label":
            label_id = details.get("reference_id")
            return CreateReturnLabelResult(
                label_id=label_id,
                label_reference=f"RET-{str(label_id)[-8:]}" if label_id else None,
                decision=decision,
                audit=audit,
                error=error,
            )
        replacement_id = details.get("reference_id")
        return CreateReplacementResult(
            replacement_order_id=(
                f"RPL-{str(replacement_id)[-8:]}" if replacement_id else None
            ),
            decision=decision,
            audit=audit,
            error=error,
        )

    def address_change_count(
        self, identity: VerifiedIdentity, order_id: str
    ) -> int:
        if not self._identity_matches(identity, order_id):
            raise PermissionError("Identity verification is required for this order")
        row = self.connection.execute(
            "SELECT address_change_count FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Order not found")
        return int(row["address_change_count"])

    def change_shipping_address(
        self,
        identity: VerifiedIdentity,
        order_id: str,
        address: AddressInput,
        idempotency_key: UUID,
        decision: PolicyDecision,
    ) -> ChangeShippingAddressResult:
        if not self._identity_matches(identity, order_id):
            raise PermissionError("Identity verification is required for this order")
        existing = self._existing_audit(idempotency_key)
        if existing:
            details = json.loads(existing["details_json"])
            return ChangeShippingAddressResult(
                address_id=details.get("address_id"),
                change_count=details["change_count"],
                decision=decision,
                audit=self._audit_record(existing),
                error=(
                    None
                    if existing["outcome"] == "committed"
                    else ToolError(code="policy_denied", message=decision.reason)
                ),
            )

        current_count = self.address_change_count(identity, order_id)
        address_id = uuid4() if decision.allowed else None
        new_count = current_count + 1 if decision.allowed else current_count
        with self.connection:
            if address_id:
                self.connection.execute(
                    """
                    INSERT INTO addresses (
                        id, customer_id, line1, line2, city, region,
                        postal_code, country_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(address_id),
                        str(identity.customer_id),
                        address.line1,
                        address.line2,
                        address.city,
                        address.region,
                        address.postal_code,
                        address.country_code,
                    ),
                )
                self.connection.execute(
                    """
                    UPDATE orders
                    SET shipping_address_id = ?, address_change_count = ?
                    WHERE id = ?
                    """,
                    (str(address_id), new_count, order_id),
                )
            audit = self._insert_audit(
                order_id=order_id,
                idempotency_key=idempotency_key,
                operation="change_shipping_address",
                outcome="committed" if decision.allowed else "denied",
                decision=decision,
                details={
                    "address_id": str(address_id) if address_id else None,
                    "change_count": new_count,
                },
            )
        return ChangeShippingAddressResult(
            address_id=address_id,
            change_count=new_count,
            decision=decision,
            audit=audit,
            error=(
                None
                if decision.allowed
                else ToolError(code="policy_denied", message=decision.reason)
            ),
        )

    def update_contact_preferences(
        self,
        identity: VerifiedIdentity,
        email_opt_in: bool | None,
        sms_opt_in: bool | None,
        idempotency_key: UUID,
        decision: PolicyDecision,
    ) -> UpdateContactPreferencesResult:
        if not self._identity_matches(identity, identity.order_id):
            raise PermissionError("Identity verification is required")
        existing = self._existing_audit(idempotency_key)
        if existing:
            return UpdateContactPreferencesResult(
                updated=existing["outcome"] == "committed",
                decision=decision,
                audit=self._audit_record(existing),
            )
        assignments: list[str] = []
        values: list[object] = []
        if email_opt_in is not None:
            assignments.append("email_opt_in = ?")
            values.append(int(email_opt_in))
        if sms_opt_in is not None:
            assignments.append("sms_opt_in = ?")
            values.append(int(sms_opt_in))
        if not assignments:
            raise ValueError("At least one contact preference is required")
        with self.connection:
            self.connection.execute(
                f"UPDATE customers SET {', '.join(assignments)} WHERE id = ?",
                (*values, str(identity.customer_id)),
            )
            audit = self._insert_audit(
                order_id=identity.order_id,
                idempotency_key=idempotency_key,
                operation="update_contact_preferences",
                outcome="committed",
                decision=decision,
                details={
                    "email_opt_in": email_opt_in,
                    "sms_opt_in": sms_opt_in,
                },
            )
        return UpdateContactPreferencesResult(
            updated=True,
            decision=decision,
            audit=audit,
        )

    def lookup_audit_actions(self, audit_ids: list[UUID]) -> LookupAuditActionsResult:
        records = []
        missing = []
        for audit_id in audit_ids:
            row = self.connection.execute(
                "SELECT * FROM audit_log WHERE id = ?",
                (str(audit_id),),
            ).fetchone()
            if row is None:
                missing.append(audit_id)
            else:
                records.append(self._audit_record(row))
        return LookupAuditActionsResult(
            records=records,
            missing_audit_ids=missing,
        )
