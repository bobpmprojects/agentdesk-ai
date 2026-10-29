"""Supervisor for the M1 verified order-status vertical slice."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from agentdesk.agents.identity import IdentityAgent
from agentdesk.agents.orders import OrdersAgent
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
    OrdersAgentInput,
    PlanStep,
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
