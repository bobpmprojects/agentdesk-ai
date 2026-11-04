"""Framework-neutral Supervisor facade backed by an explicit LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from uuid import NAMESPACE_URL, UUID, uuid5

from agentdesk.agents.graph import AgentDeskGraph
from agentdesk.agents.planner import FALLBACK_QUESTION, PlannerAgent
from agentdesk.config import Settings
from agentdesk.db.repository import Repository
from agentdesk.runtime.redaction import redact_free_text
from agentdesk.runtime.replay import LiveCall
from agentdesk.schemas.agents import (
    ContinueConversationInput,
    ConversationTurnOutput,
    MultiIntentSupervisorInput,
    MultiIntentSupervisorOutput,
    PolicySupervisorInput,
    PolicySupervisorOutput,
    RefundSupervisorInput,
    RefundSupervisorOutput,
    StartResolutionInput,
    SupervisorInput,
    SupervisorOutput,
)
from agentdesk.schemas.planner import (
    AgentTurnOutput,
    CustomerTurnInput,
    ExecutedStep,
    PlannerIntent,
)


class Supervisor:
    """Stable application API; LangGraph remains internal and replaceable."""

    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        *,
        live_call: LiveCall | None = None,
        on_node: Callable[[str], None] | None = None,
    ) -> None:
        self.runtime = AgentDeskGraph(
            repository,
            settings,
            live_call=live_call,
            on_node=on_node,
        )
        self.trace = self.runtime.trace
        self.planner = PlannerAgent(settings, self.trace, live_call=live_call)

    def handle_message(self, request: CustomerTurnInput) -> AgentTurnOutput:
        """Free-text entry point: the model plans, then code verifies and executes.

        1. Redact PII from the message before any model sees it.
        2. The planner (LLM) decides which intents the message contains, in order.
        3. Code checks identity before any order data is read.
        4. Each intent runs through the existing tested flow, where the policy
           engine approves or denies every action.
        """
        redacted = redact_free_text(request.context.customer_message)
        context = request.context.model_copy(update={"customer_message": redacted})
        plan = self.planner.plan(context)
        if plan.needs_clarification or not plan.intents:
            return AgentTurnOutput(
                redacted_message=redacted,
                plan=plan,
                final_reply=plan.clarifying_question or FALLBACK_QUESTION,
            )

        steps: list[ExecutedStep] = []
        replies: list[str] = []
        order_intents = [i for i in plan.intents if i != "policy_question"]
        identity = None
        item_id = None
        if order_intents:
            identity, item_id, gate_step, gate_reply = self._identity_gate(
                request, order_intents[0]
            )
            if gate_step is not None:
                steps.append(gate_step)
                replies.append(gate_reply)

        handled_address = False
        for intent in plan.intents:
            if intent == "policy_question":
                result = self.run_policy(PolicySupervisorInput(context=context))
                steps.append(
                    ExecutedStep(
                        intent=intent,
                        outcome="answered",
                        detail=(
                            "Answered with a cited policy section."
                            if result.grounded
                            else "No policy section covers this; no policy claim made."
                        ),
                    )
                )
                replies.append(result.final_reply)
                continue
            if identity is None or item_id is None:
                continue
            if intent == "order_status":
                result = self.run(
                    SupervisorInput(
                        context=context, order_id=request.order_id, email=request.email
                    )
                )
                steps.append(
                    ExecutedStep(
                        intent=intent, outcome="completed", detail="Order facts read from the database."
                    )
                )
                replies.append(result.final_reply)
            elif intent == "refund" and "address_change" in plan.intents:
                handled_address = True
                if request.new_address is None:
                    steps.append(
                        ExecutedStep(
                            intent="address_change",
                            outcome="needs_input",
                            detail="New address must come from the address form, not free text.",
                        )
                    )
                    replies.append(
                        "Please enter the new shipping address in the address fields so I can "
                        "handle the refund and the address change together."
                    )
                    continue
                multi = self.run_multi_intent(
                    MultiIntentSupervisorInput(
                        context=context,
                        order_id=request.order_id,
                        email=request.email,
                        item_id=item_id,
                        new_address=request.new_address,
                        refund_idempotency_key=_key("refund", request.order_id, item_id),
                        address_idempotency_key=_key("address", request.order_id, item_id),
                        replacement_idempotency_key=_key("replacement", request.order_id, item_id),
                    )
                )
                done = {action.action_type for action in multi.actions}
                steps.append(_step("refund", "refund" in done, "Policy engine decision on the refund."))
                steps.append(
                    _step(
                        "address_change",
                        "change_shipping_address" in done,
                        "Policy engine decision on the address change.",
                    )
                )
                replies.append(multi.final_reply)
            elif intent == "refund":
                refund = self.run_refund(
                    RefundSupervisorInput(
                        context=context,
                        order_id=request.order_id,
                        email=request.email,
                        item_id=item_id,
                        reason=plan.reason or "other",
                        idempotency_key=_key("refund", request.order_id, item_id),
                    )
                )
                approved = refund.resolution is not None and refund.resolution.action is not None
                decision = refund.resolution.policy_decision if refund.resolution else None
                steps.append(
                    _step(
                        "refund",
                        approved,
                        f"Policy rule {decision.rule_id}: {decision.reason}"
                        if decision
                        else "No policy decision was returned.",
                    )
                )
                replies.append(refund.final_reply)
            elif intent == "address_change" and not handled_address:
                steps.append(
                    ExecutedStep(
                        intent=intent,
                        outcome="unsupported",
                        detail="Address-only changes are not wired in this version; nothing was changed.",
                    )
                )
                replies.append(
                    "I can't change a shipping address on its own in this version, so nothing "
                    "was changed. A refund request can include an address change."
                )

        return AgentTurnOutput(
            redacted_message=redacted,
            plan=plan,
            steps=steps,
            final_reply="\n\n".join(reply for reply in replies if reply),
        )

    def _identity_gate(
        self, request: CustomerTurnInput, intent: PlannerIntent
    ) -> tuple[object | None, str | None, ExecutedStep | None, str]:
        """Identity before any order read: no match, no data."""
        if not request.order_id or request.email is None:
            return (
                None,
                None,
                ExecutedStep(
                    intent=intent,
                    outcome="needs_input",
                    detail="Order ID and email are required before any order data is read.",
                ),
                (
                    "To help with your order, please enter your order ID and the email "
                    "address on the order."
                ),
            )
        result = self.runtime.repository.verify_identity(
            request.order_id, request.email.get_secret_value()
        )
        if not result.verified or result.identity is None:
            return (
                None,
                None,
                ExecutedStep(
                    intent=intent,
                    outcome="denied",
                    detail="Identity check failed; no order data was read.",
                ),
                (
                    "I couldn't verify that order ID and email combination. Please check both "
                    "values and try again."
                ),
            )
        item_id = self.runtime.repository.get_order_item(result.identity, request.order_id)
        return result.identity, item_id, None, ""

    def run(self, request: SupervisorInput) -> SupervisorOutput:
        return self.runtime.run_order_status(request)

    def run_refund(self, request: RefundSupervisorInput) -> RefundSupervisorOutput:
        return self.runtime.run_refund(request)

    def run_multi_intent(
        self, request: MultiIntentSupervisorInput
    ) -> MultiIntentSupervisorOutput:
        return self.runtime.run_multi_intent(request)

    def run_policy(
        self, request: PolicySupervisorInput
    ) -> PolicySupervisorOutput:
        return self.runtime.run_policy(request)

    def start_resolution(
        self, request: StartResolutionInput
    ) -> ConversationTurnOutput:
        return self.runtime.start_resolution(request)

    def continue_conversation(
        self, request: ContinueConversationInput
    ) -> ConversationTurnOutput:
        return self.runtime.continue_conversation(request)

    def mermaid(self, active_node: str | None = None) -> str:
        return self.runtime.mermaid(active_node)


def _key(operation: str, order_id: str | None, item_id: str) -> UUID:
    """Same request on the same order item, same key: asking twice writes once."""
    return uuid5(NAMESPACE_URL, f"agentdesk:{operation}:{order_id}:{item_id}")


def _step(intent: PlannerIntent, completed: bool, detail: str) -> ExecutedStep:
    return ExecutedStep(
        intent=intent, outcome="completed" if completed else "denied", detail=detail
    )
