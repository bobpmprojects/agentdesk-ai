"""The AgentDesk team: three agents propose, deterministic code decides.

Agents (an LLM chooses what to do next):
  1. triage_agent      reads the message and plans the intents
  2. resolution_agent  investigates an order problem with read-only tools, proposes a fix
  3. policy_agent      searches the policies with its own queries, decides if they answer it

Code (same input, same output, every time):
  redact          masks PII before any model sees the text
  identity_gate   order ID + email must match before any order data is read
  dispatch        runs the planned intents in order
  workers         orders and account actions, plus executing approved proposals
  policy engine   allows or denies every action, at proposal time and at write time
  reply_check     blocks unsupported claims and invented numbers in the reply
"""

from __future__ import annotations

import json
import operator
import re
from collections.abc import Callable
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.graph import END, START, StateGraph
from pydantic import Field

from agentdesk.agents.account import AccountAgent
from agentdesk.agents.graph import claims_unwritten_refund
from agentdesk.agents.orders import OrdersAgent
from agentdesk.agents.planner import FALLBACK_QUESTION, PlannerAgent
from agentdesk.agents.policy_agent import PolicyAgent
from agentdesk.agents.resolution_agent import ResolutionAgent
from agentdesk.agents.returns_refunds import ReturnsRefundsAgent
from agentdesk.config import Settings
from agentdesk.db.repository import Repository
from agentdesk.policy.engine import PolicyCheckInput, PolicyEngine
from agentdesk.runtime.redaction import redact_free_text
from agentdesk.runtime.replay import LiveCall, ModelMessage, ModelRequest, ReplayCache
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.agents import (
    AccountAgentInput,
    OrdersAgentInput,
    ReturnsRefundsAgentInput,
)
from agentdesk.schemas.common import AgentContext, ContractModel
from agentdesk.schemas.planner import (
    AgentStep,
    AgentTurnOutput,
    CustomerTurnInput,
    ExecutedStep,
    PlannerIntent,
    PlannerOutput,
)
from agentdesk.schemas.tools import ValidateCitationsArgs
from agentdesk.tools.policy_search import validate_citations

NOT_COVERED_REPLY = (
    "I couldn't find that answer in the Northwind Goods policy documents, so I can't "
    "make a policy claim about it."
)
IDENTITY_FAILED_REPLY = (
    "I couldn't verify that order ID and email combination. Please check both values and try again."
)
NEEDS_ORDER_REPLY = (
    "To help with your order, please enter your order ID and the email address on the order."
)
NEEDS_ADDRESS_REPLY = (
    "Please enter the new shipping address in the address fields so I can check that change."
)
NOT_RESOLVED_REPLY = "I wasn't able to resolve this automatically, so nothing was changed."
REPLY_TEMPLATE_VERSION = "m7-reply-v1"
_DOLLARS = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
_OFFER_WORDS = {
    "store_credit": "store credit",
    "replacement": "a replacement",
    "refund": "a refund",
}
_ORDER_INTENTS = {"order_status", "refund", "address_change"}


class TeamState(ContractModel):
    request: CustomerTurnInput
    context: AgentContext | None = None
    plan: PlannerOutput | None = None
    protected: AgentContext | None = None
    item_id: str | None = None
    queue: list[PlannerIntent] = Field(default_factory=list)
    steps: list[ExecutedStep] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    fixed_replies: list[str] = Field(default_factory=list)
    agent_steps: list[AgentStep] = Field(default_factory=list)
    code_checks: list[str] = Field(default_factory=list)
    preset_reply: str | None = None
    writer_reply: str = ""
    final_reply: str = ""
    visited: Annotated[list[str], operator.add] = Field(default_factory=list)


def _key(operation: str, order_id: str | None, item_id: str | None) -> UUID:
    """Same request on the same order item, same key: asking twice writes once."""
    return uuid5(NAMESPACE_URL, f"agentdesk:{operation}:{order_id}:{item_id}")


def _amounts(text: str) -> set[str]:
    return {f"{float(m.replace(',', '')):.2f}" for m in _DOLLARS.findall(text)}


def template_reply(facts: list[dict[str, Any]]) -> str:
    """Deterministic reply built only from code's decisions; used when the writer is blocked."""
    lines = []
    for fact in facts:
        if fact["intent"] == "refund":
            if fact["action_committed"]:
                lines.append(f"Your refund of ${fact['amount']} has been processed.")
            else:
                line = f"I can't approve this cash refund: {fact['reason']}"
                offers = [_OFFER_WORDS[o] for o in fact.get("offered_alternatives", [])]
                if offers:
                    line += f" I can offer {' or '.join(offers)} instead, if you'd like."
                lines.append(line)
        elif fact["intent"] == "address_change":
            lines.append(
                "Your shipping address has been updated."
                if fact["action_committed"]
                else f"I couldn't change the shipping address: {fact['reason']}"
            )
        elif fact["intent"] == "order_status":
            lines.append(f"Your order {fact['order_id']} is {fact['status']}.")
    return " ".join(lines)


class AgentTeam:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        trace: TraceCollector,
        *,
        live_call: LiveCall | None = None,
        on_node: Callable[[str], None] | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.trace = trace
        self.live_call = live_call
        self.on_node = on_node
        self.policy = PolicyEngine()
        self.triage = PlannerAgent(settings, trace, live_call=live_call)
        self.resolution = ResolutionAgent(repository, settings, trace, live_call=live_call)
        self.policy_agent = PolicyAgent(settings.policies_dir, settings, trace, live_call=live_call)
        self.replay = ReplayCache(settings.replay_dir, settings.llm_mode)
        self.compiled = self._build()

    # ---- graph -------------------------------------------------------------------------

    def _build(self):
        builder = StateGraph(TeamState)
        builder.add_node("redact", self._redact)
        builder.add_node("triage_agent", self._triage)
        builder.add_node("identity_gate", self._identity_gate)
        builder.add_node("dispatch", self._dispatch)
        builder.add_node("resolution_agent", self._resolution_agent)
        builder.add_node("policy_agent", self._policy_agent)
        builder.add_node("orders_worker", self._orders_worker)
        builder.add_node("account_worker", self._account_worker)
        builder.add_node("reply_writer", self._reply_writer)
        builder.add_node("reply_check", self._reply_check)
        builder.add_edge(START, "redact")
        builder.add_edge("redact", "triage_agent")
        builder.add_edge("triage_agent", "identity_gate")
        builder.add_edge("identity_gate", "dispatch")
        builder.add_conditional_edges(
            "dispatch",
            self._route,
            {
                "resolution_agent": "resolution_agent",
                "policy_agent": "policy_agent",
                "orders_worker": "orders_worker",
                "account_worker": "account_worker",
                "reply_writer": "reply_writer",
            },
        )
        for node in ("resolution_agent", "policy_agent", "orders_worker", "account_worker"):
            builder.add_edge(node, "dispatch")
        builder.add_edge("reply_writer", "reply_check")
        builder.add_edge("reply_check", END)
        return builder.compile()

    def run(self, request: CustomerTurnInput) -> AgentTurnOutput:
        result = TeamState.model_validate(
            self.compiled.invoke(TeamState(request=request).model_dump(mode="python"))
        )
        assert result.plan is not None and result.context is not None
        return AgentTurnOutput(
            redacted_message=result.context.customer_message,
            plan=result.plan,
            steps=result.steps,
            agent_steps=result.agent_steps,
            code_checks=result.code_checks,
            final_reply=result.final_reply,
        )

    def mermaid(self, active_node: str | None = None) -> str:
        diagram = self.compiled.get_graph().draw_mermaid()
        for agent in ("triage_agent", "resolution_agent", "policy_agent"):
            diagram += f"\nstyle {agent} fill:#fbe4d3,stroke:#b4501a"
        if active_node:
            diagram += f"\nstyle {active_node} fill:#ffcc66,stroke:#9a6700,stroke-width:3px"
        return diagram

    def _enter(self, node: str) -> dict[str, Any]:
        if self.on_node:
            self.on_node(node)
        return {"visited": [node]}

    @staticmethod
    def _route(state: TeamState) -> str:
        if not state.queue:
            return "reply_writer"
        return {
            "refund": "resolution_agent",
            "policy_question": "policy_agent",
            "order_status": "orders_worker",
            "address_change": "account_worker",
        }[state.queue[0]]

    # ---- code nodes ----------------------------------------------------------------------

    def _redact(self, state: TeamState) -> dict[str, Any]:
        update = self._enter("redact")
        message = state.request.context.customer_message
        update["context"] = state.request.context.model_copy(
            update={"customer_message": redact_free_text(message)}
        )
        return update

    def _identity_gate(self, state: TeamState) -> dict[str, Any]:
        update = self._enter("identity_gate")
        order_intents = [i for i in state.queue if i in _ORDER_INTENTS]
        if not order_intents:
            return update
        request = state.request
        failure: tuple[str, str, str] | None = None
        if not request.order_id or request.email is None:
            failure = ("needs_input", "Order ID and email are required first.", NEEDS_ORDER_REPLY)
        else:
            verified = self.repository.verify_identity(
                request.order_id, request.email.get_secret_value()
            )
            if verified.verified and verified.identity is not None:
                update["protected"] = state.context.model_copy(
                    update={"identity": verified.identity, "active_order_id": request.order_id}
                )
                update["item_id"] = self.repository.get_order_item(
                    verified.identity, request.order_id
                )
                return update
            failure = (
                "denied",
                "Identity check failed; no order data was read.",
                IDENTITY_FAILED_REPLY,
            )
        outcome, detail, reply = failure
        update["queue"] = [i for i in state.queue if i not in _ORDER_INTENTS]
        update["steps"] = [
            *state.steps,
            ExecutedStep(intent=order_intents[0], outcome=outcome, detail=detail),
        ]
        update["fixed_replies"] = [*state.fixed_replies, reply]
        return update

    def _dispatch(self, state: TeamState) -> dict[str, Any]:
        return self._enter("dispatch")

    def _orders_worker(self, state: TeamState) -> dict[str, Any]:
        update = self._enter("orders_worker")
        order = OrdersAgent(self.repository).run(
            OrdersAgentInput(context=state.protected, task="status")
        )
        fact = {
            "intent": "order_status",
            "order_id": order.order_id,
            "status": str(order.status),
            "carrier": order.carrier,
            "tracking_number": order.tracking_number_redacted,
            "estimated_delivery": order.estimated_delivery.isoformat()
            if order.estimated_delivery
            else None,
        }
        update.update(
            queue=state.queue[1:],
            facts=[*state.facts, fact],
            steps=[
                *state.steps,
                ExecutedStep(
                    intent="order_status",
                    outcome="completed",
                    detail="Order facts read from the database.",
                ),
            ],
        )
        return update

    def _account_worker(self, state: TeamState) -> dict[str, Any]:
        update = self._enter("account_worker")
        request = state.request
        if request.new_address is None:
            update.update(
                queue=state.queue[1:],
                fixed_replies=[*state.fixed_replies, NEEDS_ADDRESS_REPLY],
                steps=[
                    *state.steps,
                    ExecutedStep(
                        intent="address_change",
                        outcome="needs_input",
                        detail="New address must come from the address form, not chat text.",
                    ),
                ],
            )
            return update
        result = AccountAgent(self.repository).run(
            AccountAgentInput(
                context=state.protected,
                task="change_shipping_address",
                new_address=request.new_address,
                idempotency_key=_key("address", request.order_id, state.item_id),
            )
        )
        decision = result.policy_decision
        update.update(
            queue=state.queue[1:],
            facts=[
                *state.facts,
                {
                    "intent": "address_change",
                    "action_committed": result.changed,
                    "rule_id": decision.rule_id,
                    "reason": decision.reason,
                },
            ],
            steps=[
                *state.steps,
                ExecutedStep(
                    intent="address_change",
                    outcome="completed" if result.changed else "denied",
                    detail=f"Policy rule {decision.rule_id}: {decision.reason}",
                ),
            ],
        )
        return update

    def _reply_check(self, state: TeamState) -> dict[str, Any]:
        """Deterministic output checks on the AI-written part of the reply."""
        update = self._enter("reply_check")
        checks = list(state.code_checks)
        writer = state.writer_reply
        if writer:
            committed_refund = any(
                f["intent"] == "refund" and f["action_committed"] for f in state.facts
            )
            allowed_amounts = (
                _amounts(json.dumps(state.facts))
                | _amounts(state.context.customer_message)
                | {f"{float(f['amount']):.2f}" for f in state.facts if f.get("amount")}
            )
            invented = _amounts(writer) - allowed_amounts
            if not committed_refund and claims_unwritten_refund(writer):
                checks.append(
                    "Reply claimed a refund no tool wrote; replaced with the code template."
                )
                writer = template_reply(state.facts)
            elif invented:
                checks.append(
                    f"Reply used amounts not in the facts ({sorted(invented)}); replaced."
                )
                writer = template_reply(state.facts)
            else:
                checks.append("Reply passed: no unsupported refund claim, no invented amounts.")
        parts = [state.preset_reply] if state.preset_reply else []
        parts += [writer] if writer else []
        parts += state.fixed_replies
        update.update(code_checks=checks, final_reply="\n\n".join(p for p in parts if p))
        return update

    # ---- agent nodes ---------------------------------------------------------------------

    def _triage(self, state: TeamState) -> dict[str, Any]:
        update = self._enter("triage_agent")
        plan = self.triage.plan(state.context)
        update["plan"] = plan
        update["agent_steps"] = [
            *state.agent_steps,
            AgentStep(
                agent="triage_agent", thought=plan.rationale, args={"intents": list(plan.intents)}
            ),
        ]
        if plan.needs_clarification or not plan.intents:
            update["preset_reply"] = plan.clarifying_question or FALLBACK_QUESTION
            update["queue"] = []
        else:
            update["queue"] = list(plan.intents)
        return update

    def _resolution_agent(self, state: TeamState) -> dict[str, Any]:
        update = self._enter("resolution_agent")
        checks = list(state.code_checks)
        protected = state.protected
        result = self.resolution.run(
            protected, requested="refund", reason=state.plan.reason if state.plan else None
        )
        agent_steps = [*state.agent_steps, *result.steps]
        proposal = result.proposal
        if proposal is None:
            checks.append(f"Resolution agent stopped ({result.stop_reason}); nothing was changed.")
            update.update(
                queue=state.queue[1:],
                agent_steps=agent_steps,
                code_checks=checks,
                fixed_replies=[*state.fixed_replies, NOT_RESOLVED_REPLY],
                steps=[
                    *state.steps,
                    ExecutedStep(
                        intent="refund",
                        outcome="escalated",
                        detail="Agent did not finish; no action taken.",
                    ),
                ],
            )
            return update

        order = self.repository.get_order(protected.identity, protected.identity.order_id)
        execute = proposal.execute
        offers = list(proposal.offer)
        if execute is not None and execute != "refund":
            checks.append(
                f"Agent proposed executing {execute}, but the customer asked for a refund; "
                "code turned it into an offer."
            )
            offers.append(execute)
            execute = None
        allowed_offers = []
        for option in dict.fromkeys(offers):
            if option == "refund":
                continue
            decision = self.policy.check(self._policy_input(order, option))
            if decision.allowed:
                allowed_offers.append(option)
            else:
                checks.append(f"Dropped offer of {option}: {decision.rule_id}.")

        if execute == "refund":
            outcome = ReturnsRefundsAgent(self.repository, self.policy).run(
                ReturnsRefundsAgentInput(
                    context=protected,
                    task="refund",
                    item_id=state.item_id,
                    reason=(state.plan.reason if state.plan else None) or "other",
                    idempotency_key=_key("refund", protected.identity.order_id, state.item_id),
                )
            )
            decision = outcome.policy_decision
            committed = outcome.action is not None
            if not committed:
                checks.append(
                    f"Agent proposed the refund, but the write-time policy check denied it "
                    f"({decision.rule_id})."
                )
        else:
            decision = self.policy.check(self._policy_input(order, "refund"))
            committed = False
        detail = f"Policy rule {decision.rule_id}: {decision.reason}"
        if allowed_offers:
            detail += f" Offered: {', '.join(allowed_offers)}."
        update.update(
            queue=state.queue[1:],
            agent_steps=agent_steps,
            code_checks=checks,
            facts=[
                *state.facts,
                {
                    "intent": "refund",
                    "requested": "cash refund",
                    "action_committed": committed,
                    "amount": str(order.total.amount) if committed else None,
                    "rule_id": decision.rule_id,
                    "reason": decision.reason,
                    "offered_alternatives": allowed_offers,
                },
            ],
            steps=[
                *state.steps,
                ExecutedStep(
                    intent="refund",
                    outcome="completed" if committed else "denied",
                    detail=detail,
                    decided_by="code (policy engine), on the Resolution agent's proposal",
                ),
            ],
        )
        return update

    def _policy_agent(self, state: TeamState) -> dict[str, Any]:
        update = self._enter("policy_agent")
        checks = list(state.code_checks)
        result = self.policy_agent.run(state.context)
        answer = result.answer
        reply = NOT_COVERED_REPLY
        detail = "Agent concluded no policy section covers this; code used the fixed reply."
        if answer is not None and answer.covered:
            unseen = [c for c in answer.citations if c not in result.retrieved]
            citations = [result.retrieved[c] for c in answer.citations if c in result.retrieved]
            real = validate_citations(
                self.settings.policies_dir, ValidateCitationsArgs(citations=citations)
            ).valid
            if not answer.citations or unseen or not real or not answer.answer:
                checks.append(
                    "Policy answer blocked: citations missing or not retrieved in this run "
                    f"({unseen or 'none given'})."
                )
                detail = "Agent's answer failed the citation check; code used the fixed reply."
            else:
                reply = f"{answer.answer} [{', '.join(answer.citations)}]"
                detail = f"Answered from {', '.join(answer.citations)}; citations verified."
                checks.append(
                    "Policy citations verified: every cited section was retrieved and exists."
                )
        elif answer is None:
            checks.append(
                f"Policy agent stopped ({result.stop_reason}); code used the fixed reply."
            )
        update.update(
            queue=state.queue[1:],
            agent_steps=[*state.agent_steps, *result.steps],
            code_checks=checks,
            fixed_replies=[*state.fixed_replies, reply],
            steps=[
                *state.steps,
                ExecutedStep(
                    intent="policy_question",
                    outcome="answered",
                    detail=detail,
                    decided_by="code (citation check), on the Policy agent's answer",
                ),
            ],
        )
        return update

    def _reply_writer(self, state: TeamState) -> dict[str, Any]:
        """One LLM call that phrases code's decisions. It decides nothing."""
        update = self._enter("reply_writer")
        if not state.facts:
            return update
        request = ModelRequest(
            provider=self.settings.model_provider,
            model_id=self.settings.model_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Write one concise, friendly customer-service reply in plain text that "
                        "reports these results. Use only the facts. Say an action was done only "
                        "when action_committed is true. Present offered_alternatives as offers the "
                        "customer can accept, not as done. Do not add amounts, dates or promises "
                        "that are not in the facts. No headings or bullet points."
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=(
                        f"Customer message: {state.context.customer_message}\n"
                        f"Results decided by the store's systems: {json.dumps(state.facts, sort_keys=True)}"
                    ),
                ),
            ],
            template_version=REPLY_TEMPLATE_VERSION,
            tool_schema_version="m7-v1",
        )
        response = self.replay.invoke(request, self.live_call)
        update["writer_reply"] = response.text.strip()
        return update

    # ---- helpers -------------------------------------------------------------------------

    @staticmethod
    def _policy_input(order, option: str) -> PolicyCheckInput:
        operation = {"refund": "refund", "store_credit": "store_credit", "replacement": "replace"}[
            option
        ]
        return PolicyCheckInput(
            operation=operation,
            identity_verified=True,
            order_status=order.status,
            order_total=order.total,
            requested_amount=order.total if option == "refund" else None,
            delivered_at=order.delivered_at,
        )
