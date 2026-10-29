"""Account specialist for address and contact-preference changes."""

from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyEngine
from agentdesk.schemas.agents import AccountAgentInput, AccountAgentOutput
from agentdesk.schemas.common import ActionClaim
from agentdesk.schemas.tools import (
    ChangeShippingAddressArgs,
    UpdateContactPreferencesArgs,
)
from agentdesk.tools.account import (
    change_shipping_address,
    update_contact_preferences,
)


class AccountAgent:
    def __init__(
        self, repository: Repository, policy: PolicyEngine | None = None
    ) -> None:
        self.repository = repository
        self.policy = policy or PolicyEngine()

    def run(self, request: AccountAgentInput) -> AccountAgentOutput:
        identity = request.context.identity
        if identity is None:
            raise PermissionError("Identity verification is required before account writes")

        if request.task == "change_shipping_address":
            if request.new_address is None:
                raise ValueError("A new address is required")
            result = change_shipping_address(
                self.repository,
                self.policy,
                ChangeShippingAddressArgs(
                    identity=identity,
                    order_id=identity.order_id,
                    address=request.new_address,
                    idempotency_key=request.idempotency_key,
                    replacement_context=request.replacement_context,
                ),
            )
            action_type = "change_shipping_address"
            description = "Shipping address changed."
        else:
            result = update_contact_preferences(
                self.repository,
                self.policy,
                UpdateContactPreferencesArgs(
                    identity=identity,
                    email_opt_in=request.email_opt_in,
                    sms_opt_in=request.sms_opt_in,
                    idempotency_key=request.idempotency_key,
                ),
            )
            action_type = "update_contact_preferences"
            description = "Contact preferences updated."

        changed = result.decision.allowed and result.audit.outcome == "committed"
        return AccountAgentOutput(
            changed=changed,
            policy_decision=result.decision,
            action=(
                ActionClaim(
                    action_type=action_type,
                    audit_id=result.audit.audit_id,
                    order_id=identity.order_id,
                    description=description,
                )
                if changed
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
