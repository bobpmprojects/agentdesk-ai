"""Supervisor for the M1 verified order-status vertical slice."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from agentdesk.agents.account import AccountAgent
from agentdesk.agents.identity import IdentityAgent
from agentdesk.agents.orders import OrdersAgent
from agentdesk.agents.returns_refunds import ReturnsRefundsAgent
from agentdesk.config import Settings
from agentdesk.db.repository import Repository
from agentdesk.runtime.replay import (
    LiveCall,
    ModelMessage,
    ModelRequest,
    ReplayCache,
)
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.agents import (
    IdentityAgentInput,
    AccountAgentInput,
    MultiIntentSupervisorInput,
    MultiIntentSupervisorOutput,
    OrdersAgentInput,
    PlanStep,
    RefundSupervisorInput,
    RefundSupervisorOutput,
    ReturnsRefundsAgentInput,
    SupervisorInput,
    SupervisorOutput,
)
from agentdesk.schemas.common import TraceEvent


class Supervisor:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        *,
        live_call: LiveCall | None = None,
    ) -> None:
        self.settings = settings
        self.identity_agent = IdentityAgent(repository)
        self.orders_agent = OrdersAgent(repository)
        self.returns_refunds_agent = ReturnsRefundsAgent(repository)
        self.account_agent = AccountAgent(repository)
        self.replay = ReplayCache(settings.replay_dir, settings.llm_mode)
        self.live_call = live_call
        self.trace = TraceCollector()

    def _trace(
        self,
        request: SupervisorInput,
        event_type: str,
        agent: str,
        *,
        tool: str | None = None,
        args: dict[str, object] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: Decimal = Decimal("0"),
    ) -> None:
        self.trace.add(
            TraceEvent(
                event_id=uuid4(),
                conversation_id=request.context.conversation_id,
                turn_id=request.context.turn_id,
                timestamp=datetime.now(UTC),
                event_type=event_type,
                agent=agent,
                tool=tool,
                args_redacted=args or {},
                latency_ms=0,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        )

    def run(self, request: SupervisorInput) -> SupervisorOutput:
        plan = [
            PlanStep(
                step_id="verify",
                intent="order_status",
                specialist="identity",
                requested_operation="verify_identity",
            ),
            PlanStep(
                step_id="lookup",
                intent="order_status",
                specialist="orders",
                depends_on=["verify"],
                requested_operation="get_order_and_tracking",
            ),
        ]
        self._trace(request, "agent_start", "supervisor", args={"plan": plan})
        self._trace(
            request,
            "tool_start",
            "identity",
            tool="verify_identity",
            args={"order_id": request.order_id, "email": request.email.get_secret_value()},
        )
        identity_result = self.identity_agent.run(
            IdentityAgentInput(
                context=request.context,
                order_id=request.order_id,
                email=request.email,
            )
        )
        self._trace(
            request,
            "tool_end",
            "identity",
            tool="verify_identity",
            args={"verified": identity_result.verified},
        )
        if not identity_result.verified or identity_result.identity is None:
            reply = (
                "I couldn't verify that order ID and email combination. "
                "Please check both values and try again."
            )
            self._trace(request, "agent_end", "supervisor")
            return SupervisorOutput(
                intents=["order_status"],
                plan=plan,
                final_reply=reply,
            )

        protected_context = request.context.model_copy(
            update={
                "identity": identity_result.identity,
                "active_order_id": request.order_id,
            }
        )
        self._trace(
            request,
            "tool_start",
            "orders",
            tool="get_order_and_tracking",
            args={"order_id": request.order_id},
        )
        order = self.orders_agent.run(
            OrdersAgentInput(context=protected_context, task="status")
        )
        self._trace(
            request,
            "tool_end",
            "orders",
            tool="get_order_and_tracking",
            args=order.model_dump(mode="json"),
        )

        model_request = ModelRequest(
            provider=self.settings.model_provider,
            model_id=self.settings.model_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Write one concise customer-service reply using only the supplied "
                        "order facts. Do not invent promises, dates, or actions."
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=(
                        f"Customer question: {request.context.customer_message}\n"
                        f"Verified order facts: {order.model_dump_json()}"
                    ),
                ),
            ],
            template_version="m1-order-status-v1",
            tool_schema_version="m1-v1",
        )
        response = self.replay.invoke(model_request, self.live_call)
        self._trace(
            request,
            "model_call",
            "supervisor",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=Decimal(str(response.usage.cost_usd)),
        )
        self._trace(request, "agent_end", "supervisor")
        return SupervisorOutput(
            intents=["order_status"],
            plan=plan,
            final_reply=response.text,
        )

    def run_refund(self, request: RefundSupervisorInput) -> RefundSupervisorOutput:
        plan = [
            PlanStep(
                step_id="verify",
                intent="refund",
                specialist="identity",
                requested_operation="verify_identity",
            ),
            PlanStep(
                step_id="refund",
                intent="refund",
                specialist="returns_refunds",
                depends_on=["verify"],
                requested_operation="create_refund",
            ),
        ]
        self._trace(
            request, "agent_start", "supervisor", args={"plan": plan}
        )
        self._trace(
            request,
            "tool_start",
            "identity",
            tool="verify_identity",
            args={"order_id": request.order_id, "email": request.email.get_secret_value()},
        )
        identity_result = self.identity_agent.run(
            IdentityAgentInput(
                context=request.context,
                order_id=request.order_id,
                email=request.email,
            )
        )
        self._trace(
            request,
            "tool_end",
            "identity",
            tool="verify_identity",
            args={"verified": identity_result.verified},
        )
        if not identity_result.verified or identity_result.identity is None:
            self._trace(request, "agent_end", "supervisor")
            return RefundSupervisorOutput(
                plan=plan,
                final_reply=(
                    "I couldn't verify that order ID and email combination, "
                    "so no refund was attempted."
                ),
            )

        protected_context = request.context.model_copy(
            update={
                "identity": identity_result.identity,
                "active_order_id": request.order_id,
            }
        )
        self._trace(
            request,
            "tool_start",
            "returns_refunds",
            tool="create_refund",
            args={"order_id": request.order_id, "item_id": request.item_id},
        )
        resolution = self.returns_refunds_agent.run(
            ReturnsRefundsAgentInput(
                context=protected_context,
                task="refund",
                item_id=request.item_id,
                reason=request.reason,
                idempotency_key=request.idempotency_key,
            )
        )
        self._trace(
            request,
            "policy_decision",
            "returns_refunds",
            tool="create_refund",
            args={
                "allowed": resolution.policy_decision.allowed,
                "rule_id": resolution.policy_decision.rule_id,
            },
        )
        facts = {
            "order_id": request.order_id,
            "requested_resolution": "cash refund",
            "allowed": resolution.policy_decision.allowed,
            "amount": (
                str(resolution.amount.amount) if resolution.amount is not None else None
            ),
            "reason": resolution.policy_decision.reason,
            "alternative": resolution.policy_decision.alternative,
            "action_committed": resolution.action is not None,
        }
        model_request = ModelRequest(
            provider=self.settings.model_provider,
            model_id=self.settings.model_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Write one concise customer-service reply using only the supplied "
                        "policy facts. State an action only when action_committed is true."
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=f"Customer request: {request.context.customer_message}\nFacts: {facts}",
                ),
            ],
            template_version="m2-refund-v1",
            tool_schema_version="m2-v1",
        )
        response = self.replay.invoke(model_request, self.live_call)
        self._trace(
            request,
            "model_call",
            "supervisor",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=Decimal(str(response.usage.cost_usd)),
        )
        self._trace(request, "agent_end", "supervisor")
        return RefundSupervisorOutput(
            plan=plan,
            final_reply=response.text,
            resolution=resolution,
        )

    def run_multi_intent(
        self, request: MultiIntentSupervisorInput
    ) -> MultiIntentSupervisorOutput:
        replacement = "replace" in request.context.customer_message.lower()
        resolution_intent = "replacement" if replacement else "refund"
        if replacement:
            plan = [
                PlanStep(
                    step_id="verify",
                    intent="replacement",
                    specialist="identity",
                    requested_operation="verify_identity",
                ),
                PlanStep(
                    step_id="assess",
                    intent="replacement",
                    specialist="returns_refunds",
                    depends_on=["verify"],
                    requested_operation="assess_return",
                ),
                PlanStep(
                    step_id="address",
                    intent="address_change",
                    specialist="account",
                    depends_on=["assess"],
                    requested_operation="change_shipping_address",
                ),
                PlanStep(
                    step_id="replace",
                    intent="replacement",
                    specialist="returns_refunds",
                    depends_on=["address"],
                    requested_operation="create_replacement",
                ),
            ]
        else:
            plan = [
                PlanStep(
                    step_id="verify",
                    intent="refund",
                    specialist="identity",
                    requested_operation="verify_identity",
                ),
                PlanStep(
                    step_id="refund",
                    intent="refund",
                    specialist="returns_refunds",
                    depends_on=["verify"],
                    requested_operation="create_refund",
                ),
                PlanStep(
                    step_id="address",
                    intent="address_change",
                    specialist="account",
                    depends_on=["verify"],
                    requested_operation="change_shipping_address",
                ),
            ]
        self._trace(request, "agent_start", "supervisor", args={"plan": plan})
        identity_result = self.identity_agent.run(
            IdentityAgentInput(
                context=request.context,
                order_id=request.order_id,
                email=request.email,
            )
        )
        if not identity_result.verified or identity_result.identity is None:
            return MultiIntentSupervisorOutput(
                intents=[resolution_intent, "address_change"],
                plan=plan,
                final_reply=(
                    "I couldn't verify the order, so no requested action was attempted."
                ),
            )
        context = request.context.model_copy(
            update={
                "identity": identity_result.identity,
                "active_order_id": request.order_id,
            }
        )
        actions = []
        facts: list[dict[str, object]] = []
        if replacement:
            assessment = self.returns_refunds_agent.run(
                ReturnsRefundsAgentInput(
                    context=context,
                    task="assess_return",
                    item_id=request.item_id,
                    reason="damaged",
                )
            )
            facts.append(
                {
                    "step": "assess replacement",
                    "allowed": assessment.eligible,
                    "reason": assessment.explanation,
                }
            )
            if assessment.eligible:
                address = self.account_agent.run(
                    AccountAgentInput(
                        context=context,
                        task="change_shipping_address",
                        new_address=request.new_address,
                        idempotency_key=request.address_idempotency_key,
                        replacement_context=True,
                    )
                )
                facts.append(
                    {
                        "step": "change replacement address",
                        "allowed": address.changed,
                        "reason": address.explanation,
                    }
                )
                if address.action:
                    actions.append(address.action)
                if address.changed:
                    result = self.returns_refunds_agent.run(
                        ReturnsRefundsAgentInput(
                            context=context,
                            task="replace",
                            item_id=request.item_id,
                            reason="damaged",
                            idempotency_key=request.replacement_idempotency_key,
                        )
                    )
                    facts.append(
                        {
                            "step": "create replacement",
                            "allowed": result.eligible,
                            "reason": result.explanation,
                        }
                    )
                    if result.action:
                        actions.append(result.action)
        else:
            result = self.returns_refunds_agent.run(
                ReturnsRefundsAgentInput(
                    context=context,
                    task="refund",
                    item_id=request.item_id,
                    reason="damaged",
                    idempotency_key=request.refund_idempotency_key,
                )
            )
            facts.append(
                {
                    "step": "refund",
                    "allowed": result.eligible,
                    "amount": str(result.amount.amount) if result.amount else None,
                    "reason": result.explanation,
                }
            )
            if result.action:
                actions.append(result.action)
            address = self.account_agent.run(
                AccountAgentInput(
                    context=context,
                    task="change_shipping_address",
                    new_address=request.new_address,
                    idempotency_key=request.address_idempotency_key,
                )
            )
            facts.append(
                {
                    "step": "change original order address",
                    "allowed": address.changed,
                    "reason": address.explanation,
                }
            )
            if address.action:
                actions.append(address.action)

        model_request = ModelRequest(
            provider=self.settings.model_provider,
            model_id=self.settings.model_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Summarize the ordered results using only these facts. "
                        "Clearly distinguish completed and denied steps."
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=(
                        f"Customer request: {request.context.customer_message}\n"
                        f"Ordered step results: {facts}"
                    ),
                ),
            ],
            template_version="m3-multi-intent-v1",
            tool_schema_version="m3-v1",
        )
        response = self.replay.invoke(model_request, self.live_call)
        self._trace(
            request,
            "model_call",
            "supervisor",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=Decimal(str(response.usage.cost_usd)),
        )
        self._trace(request, "agent_end", "supervisor")
        return MultiIntentSupervisorOutput(
            intents=[resolution_intent, "address_change"],
            plan=plan,
            final_reply=response.text,
            actions=actions,
        )
