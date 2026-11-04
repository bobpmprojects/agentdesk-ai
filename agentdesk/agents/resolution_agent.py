"""Resolution agent: investigates an order problem and proposes a fix.

The agent's judgment: which remedy fits (refund, replacement or store credit), and
what to offer when the customer's request is not allowed. Its tools are read-only and
bound to the verified order, so it cannot name a different order or change anything.
Code decides afterwards what actually runs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from agentdesk.agents.tool_loop import ToolLoop
from agentdesk.config import Settings
from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyCheckInput, PolicyEngine
from agentdesk.runtime.replay import LiveCall
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.common import AgentContext, ContractModel
from agentdesk.schemas.planner import AgentStep

Remedy = Literal["refund", "store_credit", "replacement"]
_OPERATION = {"refund": "refund", "store_credit": "store_credit", "replacement": "replace"}

RESOLUTION_SYSTEM_PROMPT = """You are the Resolution agent for Northwind Goods, an online store. A customer has a problem with an order that has already been identity-verified. Investigate with your tools, then propose the best resolution.

Reply with ONLY one JSON object per turn, no prose. Either a tool call:
{"thought": "one short sentence", "tool": "<tool name>", "args": {...}}
or your final proposal:
{"thought": "one short sentence", "final": {"execute": "refund" | "store_credit" | "replacement" | null, "offer": ["store_credit" | "replacement" | "refund", ...], "reason": "one short sentence"}}

Tools (read-only; they always refer to the verified order):
- get_order_facts {}: the order's status, total and whether it is inside the 30-day window.
- check_option {"option": "refund" | "store_credit" | "replacement"}: asks the store's policy engine whether that option is allowed for this order.

Rules:
- "execute" may only be the option the customer asked for, and only after check_option says it is allowed. Otherwise set execute to null.
- If the requested option is not allowed, check alternatives and put the allowed ones in "offer". Offers are suggestions; nothing is done until the customer agrees.
- You cannot approve anything yourself; code re-checks every decision.
- Never write a dollar amount, email or address. Use at most four tool calls."""


class ResolutionProposal(ContractModel):
    execute: Remedy | None = None
    offer: list[Remedy] = Field(default_factory=list, max_length=3)
    reason: str = Field(default="", max_length=400)


class ResolutionResult(ContractModel):
    proposal: ResolutionProposal | None
    steps: list[AgentStep]
    stop_reason: str


class ResolutionAgent:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        trace: TraceCollector,
        *,
        live_call: LiveCall | None = None,
        policy: PolicyEngine | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.trace = trace
        self.live_call = live_call
        self.policy = policy or PolicyEngine()

    def run(
        self, context: AgentContext, *, requested: Remedy, reason: str | None
    ) -> ResolutionResult:
        identity = context.identity
        if identity is None:
            raise PermissionError("The Resolution agent only runs after identity verification")
        order = self.repository.get_order(identity, identity.order_id)
        if order.error:
            raise PermissionError(order.error.message)

        def get_order_facts(_: dict[str, Any]) -> dict[str, Any]:
            window = self.policy.check(self._check(order, "refund"))
            return {
                "status": str(order.status),
                "total": str(order.total.amount),
                "delivered": order.delivered_at is not None,
                "inside_30_day_window": order.delivered_at is not None
                and window.rule_id not in {"return-window-30-days", "delivery-required"},
            }

        def check_option(args: dict[str, Any]) -> dict[str, Any]:
            option = args["option"]
            if option not in _OPERATION:
                raise ValueError("option must be refund, store_credit or replacement")
            decision = self.policy.check(self._check(order, option))
            return {
                "option": option,
                "allowed": decision.allowed,
                "rule_id": decision.rule_id,
                "reason": decision.reason,
            }

        loop = ToolLoop(
            agent="resolution_agent",
            system_prompt=RESOLUTION_SYSTEM_PROMPT,
            tools={"get_order_facts": get_order_facts, "check_option": check_option},
            settings=self.settings,
            trace=self.trace,
            template_version="m7-resolution-v1",
            live_call=self.live_call,
        )
        result = loop.run(
            context,
            (
                f"Customer message: {context.customer_message}\n"
                f"The customer asked for: {requested}\n"
                f"Reason given: {reason or 'not stated'}"
            ),
        )
        proposal = None
        if result.final is not None:
            try:
                proposal = ResolutionProposal.model_validate(result.final)
            except ValueError:
                proposal = None
        return ResolutionResult(
            proposal=proposal,
            steps=result.steps,
            stop_reason=result.stop_reason if proposal else "invalid_proposal",
        )

    def _check(self, order, option: str) -> PolicyCheckInput:
        return PolicyCheckInput(
            operation=_OPERATION[option],
            identity_verified=True,
            order_status=order.status,
            order_total=order.total,
            requested_amount=order.total if option == "refund" else None,
            delivered_at=order.delivered_at,
        )
