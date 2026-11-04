"""Explicit LangGraph orchestration for AgentDesk."""

from __future__ import annotations

import operator
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import Field

from agentdesk.agents.account import AccountAgent
from agentdesk.agents.identity import IdentityAgent
from agentdesk.agents.orders import OrdersAgent
from agentdesk.agents.policy_knowledge import PolicyKnowledgeAgent
from agentdesk.agents.returns_refunds import ReturnsRefundsAgent
from agentdesk.agents.verifier import VerifierAgent
from agentdesk.config import Settings
from agentdesk.db.repository import Repository
from agentdesk.runtime.conversation import ConversationStore
from agentdesk.runtime.replay import LiveCall, ModelMessage, ModelRequest, ReplayCache
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.agents import (
    AccountAgentInput,
    AccountAgentOutput,
    ContinueConversationInput,
    ConversationState,
    ConversationTurnOutput,
    IdentityAgentInput,
    MultiIntentSupervisorInput,
    MultiIntentSupervisorOutput,
    OrdersAgentInput,
    OrdersAgentOutput,
    PlanStep,
    PolicyKnowledgeAgentInput,
    PolicyKnowledgeAgentOutput,
    PolicySupervisorInput,
    PolicySupervisorOutput,
    RefundSupervisorInput,
    RefundSupervisorOutput,
    ReturnsRefundsAgentInput,
    ReturnsRefundsAgentOutput,
    StartResolutionInput,
    SupervisorInput,
    SupervisorOutput,
    VerifierInput,
    VerifierOutput,
)
from agentdesk.schemas.common import (
    ActionClaim,
    AgentContext,
    ContractModel,
    TraceEvent,
)

GraphOperation = Literal[
    "order_status",
    "refund",
    "multi_intent",
    "policy",
    "conversation_start",
    "conversation_continue",
]


# Output guard: when no refund was written, a reply may not claim one was.
_UNSUPPORTED_REFUND_CLAIM = re.compile(
    r"\b(?:has|have|was|were|is|been)\s+(?:been\s+)?(?:processed|approved|issued|refunded|credited)\b"
    r"|\brefund(?:ed)?\s+(?:you|your)\b",
    re.IGNORECASE,
)


def _refund_denial_reply(facts: dict[str, Any]) -> str:
    reply = f"I wasn't able to approve this cash refund. {facts.get('reason') or ''}".strip()
    if "store credit" in str(facts.get("alternative") or "").lower():
        reply += " We can offer you store credit for the item instead."
    return reply



class AgentGraphState(ContractModel):
    """Validated shared state passed between every LangGraph node."""

    operation: GraphOperation
    context: AgentContext
    order_request: SupervisorInput | None = None
    refund_request: RefundSupervisorInput | None = None
    multi_request: MultiIntentSupervisorInput | None = None
    policy_request: PolicySupervisorInput | None = None
    start_request: StartResolutionInput | None = None
    continue_request: ContinueConversationInput | None = None
    protected_context: AgentContext | None = None
    route: str = ""
    phase: str = ""
    plan: list[PlanStep] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[ActionClaim] = Field(default_factory=list)
    order_details: OrdersAgentOutput | None = None
    resolution: ReturnsRefundsAgentOutput | None = None
    account_result: AccountAgentOutput | None = None
    policy_answer: PolicyKnowledgeAgentOutput | None = None
    verifier_result: VerifierOutput | None = None
    conversation_state: ConversationState | None = None
    final_reply: str = ""
    order_output: SupervisorOutput | None = None
    refund_output: RefundSupervisorOutput | None = None
    multi_output: MultiIntentSupervisorOutput | None = None
    policy_output: PolicySupervisorOutput | None = None
    conversation_output: ConversationTurnOutput | None = None
    active_node: str = ""
    visited_nodes: Annotated[list[str], operator.add] = Field(default_factory=list)


class AgentDeskGraph:
    """Compiled graph and runtime dependencies for every AgentDesk flow."""

    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        *,
        live_call: LiveCall | None = None,
        on_node: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.identity_agent = IdentityAgent(repository)
        self.orders_agent = OrdersAgent(repository)
        self.returns_refunds_agent = ReturnsRefundsAgent(repository)
        self.account_agent = AccountAgent(repository)
        self.policy_knowledge_agent = PolicyKnowledgeAgent(settings.policies_dir)
        self.verifier_agent = VerifierAgent(
            repository, settings, live_call=live_call
        )
        self.conversation_store = ConversationStore(repository.connection)
        self.replay = ReplayCache(settings.replay_dir, settings.llm_mode)
        self.live_call = live_call
        self.on_node = on_node
        self.trace = TraceCollector()
        self.compiled = self._build()

    def _build(self):
        builder = StateGraph(AgentGraphState)
        builder.add_node("supervisor", self._supervisor_node)
        builder.add_node("identity", self._identity_node)
        builder.add_node("orders", self._orders_node)
        builder.add_node("returns_refunds", self._returns_refunds_node)
        builder.add_node("account", self._account_node)
        builder.add_node("policy_knowledge", self._policy_knowledge_node)
        builder.add_node("verifier", self._verifier_node)
        builder.add_node("memory", self._memory_node)
        builder.add_node("model_reply", self._model_reply_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_edge(START, "supervisor")
        builder.add_conditional_edges(
            "supervisor",
            self._route,
            {
                "identity": "identity",
                "policy_knowledge": "policy_knowledge",
                "memory": "memory",
            },
        )
        builder.add_conditional_edges(
            "identity",
            self._route,
            {
                "orders": "orders",
                "returns_refunds": "returns_refunds",
                "finalize": "finalize",
            },
        )
        builder.add_edge("orders", "model_reply")
        builder.add_conditional_edges(
            "returns_refunds",
            self._route,
            {
                "account": "account",
                "model_reply": "model_reply",
                "finalize": "finalize",
            },
        )
        builder.add_conditional_edges(
            "account",
            self._route,
            {
                "returns_refunds": "returns_refunds",
                "model_reply": "model_reply",
            },
        )
        builder.add_edge("policy_knowledge", "verifier")
        builder.add_edge("verifier", "finalize")
        builder.add_conditional_edges(
            "memory",
            self._route,
            {
                "returns_refunds": "returns_refunds",
                "finalize": "finalize",
            },
        )
        builder.add_edge("model_reply", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile(name="agentdesk")

    @staticmethod
    def _route(state: AgentGraphState) -> str:
        return state.route

    def _enter(self, node: str) -> dict[str, Any]:
        if self.on_node:
            self.on_node(node)
        return {"active_node": node, "visited_nodes": [node]}

    def _trace(
        self,
        context: AgentContext,
        event_type: str,
        agent: str,
        *,
        tool: str | None = None,
        args: dict[str, object] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: Decimal = Decimal(0),
    ) -> None:
        self.trace.add(
            TraceEvent(
                event_id=uuid4(),
                conversation_id=context.conversation_id,
                turn_id=context.turn_id,
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

    def _supervisor_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("supervisor")
        if state.operation == "order_status":
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
            route = "identity"
        elif state.operation == "refund":
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
            route = "identity"
        elif state.operation == "multi_intent":
            request = state.multi_request
            if request is None:
                raise ValueError("Multi-intent graph state has no request")
            replacement = "replace" in request.context.customer_message.lower()
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
                update["phase"] = "assess"
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
                update["phase"] = "refund"
            route = "identity"
        elif state.operation == "policy":
            plan = [
                PlanStep(
                    step_id="retrieve",
                    intent="policy_question",
                    specialist="policy_knowledge",
                    requested_operation="search_policies",
                )
            ]
            route = "policy_knowledge"
        elif state.operation == "conversation_start":
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
            ]
            route = "identity"
        else:
            plan = []
            route = "memory"
        self._trace(state.context, "agent_start", "supervisor", args={"plan": plan})
        update.update({"plan": plan, "route": route})
        return update

    def _identity_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("identity")
        request = (
            state.order_request
            or state.refund_request
            or state.multi_request
            or state.start_request
        )
        if request is None:
            raise ValueError("Identity node has no protected request")
        self._trace(
            state.context,
            "tool_start",
            "identity",
            tool="verify_identity",
            args={"order_id": request.order_id, "email": request.email.get_secret_value()},
        )
        result = self.identity_agent.run(
            IdentityAgentInput(
                context=state.context,
                order_id=request.order_id,
                email=request.email,
            )
        )
        self._trace(
            state.context,
            "tool_end",
            "identity",
            tool="verify_identity",
            args={"verified": result.verified},
        )
        if not result.verified or result.identity is None:
            if state.operation == "order_status":
                output = SupervisorOutput(
                    intents=["order_status"],
                    plan=state.plan,
                    final_reply=(
                        "I couldn't verify that order ID and email combination. "
                        "Please check both values and try again."
                    ),
                )
                update["order_output"] = output
            elif state.operation == "refund":
                update["refund_output"] = RefundSupervisorOutput(
                    plan=state.plan,
                    final_reply=(
                        "I couldn't verify that order ID and email combination, "
                        "so no refund was attempted."
                    ),
                )
            elif state.operation == "multi_intent":
                resolution = (
                    "replacement"
                    if "replace" in state.context.customer_message.lower()
                    else "refund"
                )
                update["multi_output"] = MultiIntentSupervisorOutput(
                    intents=[resolution, "address_change"],
                    plan=state.plan,
                    final_reply=(
                        "I couldn't verify the order, so no requested action was attempted."
                    ),
                )
            else:
                conversation = ConversationState(
                    conversation_id=state.context.conversation_id,
                    updated_at=datetime.now(UTC),
                )
                self.conversation_store.save(conversation)
                update["conversation_output"] = ConversationTurnOutput(
                    final_reply=(
                        "I couldn't verify the order, so no resolution was selected."
                    ),
                    state=conversation,
                )
            update["route"] = "finalize"
            return update

        protected_context = state.context.model_copy(
            update={
                "identity": result.identity,
                "active_order_id": request.order_id,
            }
        )
        update.update(
            {
                "protected_context": protected_context,
                "route": (
                    "orders"
                    if state.operation == "order_status"
                    else "returns_refunds"
                ),
            }
        )
        return update

    def _orders_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("orders")
        if state.protected_context is None:
            raise ValueError("Orders node requires verified context")
        self._trace(
            state.context,
            "tool_start",
            "orders",
            tool="get_order_and_tracking",
            args={"order_id": state.protected_context.active_order_id or ""},
        )
        order = self.orders_agent.run(
            OrdersAgentInput(context=state.protected_context, task="status")
        )
        self._trace(
            state.context,
            "tool_end",
            "orders",
            tool="get_order_and_tracking",
            args=order.model_dump(mode="json"),
        )
        update["order_details"] = order
        return update

    def _returns_refunds_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("returns_refunds")
        context = state.protected_context
        if context is None:
            raise ValueError("Returns node requires verified context")
        if state.operation == "refund":
            request = state.refund_request
            if request is None:
                raise ValueError("Refund node has no request")
            resolution = self.returns_refunds_agent.run(
                ReturnsRefundsAgentInput(
                    context=context,
                    task="refund",
                    item_id=request.item_id,
                    reason=request.reason,
                    idempotency_key=request.idempotency_key,
                )
            )
            update.update(
                {
                    "resolution": resolution,
                    "facts": [
                        {
                            "order_id": request.order_id,
                            "requested_resolution": "cash refund",
                            "allowed": resolution.policy_decision.allowed,
                            "amount": (
                                str(resolution.amount.amount)
                                if resolution.amount is not None
                                else None
                            ),
                            "reason": resolution.policy_decision.reason,
                            "alternative": resolution.policy_decision.alternative,
                            "action_committed": resolution.action is not None,
                        }
                    ],
                    "route": "model_reply",
                }
            )
            return update

        if state.operation == "multi_intent":
            request = state.multi_request
            if request is None:
                raise ValueError("Multi-intent returns node has no request")
            facts = list(state.facts)
            actions = list(state.actions)
            replacement = "replace" in request.context.customer_message.lower()
            if replacement and state.phase == "assess":
                resolution = self.returns_refunds_agent.run(
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
                        "allowed": resolution.eligible,
                        "reason": resolution.explanation,
                    }
                )
                update.update(
                    {
                        "resolution": resolution,
                        "facts": facts,
                        "route": "account" if resolution.eligible else "model_reply",
                        "phase": "address",
                    }
                )
                return update
            if replacement:
                resolution = self.returns_refunds_agent.run(
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
                        "allowed": resolution.eligible,
                        "reason": resolution.explanation,
                    }
                )
            else:
                resolution = self.returns_refunds_agent.run(
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
                        "allowed": resolution.eligible,
                        "amount": (
                            str(resolution.amount.amount)
                            if resolution.amount is not None
                            else None
                        ),
                        "reason": resolution.explanation,
                    }
                )
            if resolution.action:
                actions.append(resolution.action)
            update.update(
                {
                    "resolution": resolution,
                    "facts": facts,
                    "actions": actions,
                    "route": "model_reply" if replacement else "account",
                    "phase": "address",
                }
            )
            return update

        if state.operation == "conversation_start":
            request = state.start_request
            if request is None:
                raise ValueError("Conversation start node has no request")
            assessment = self.returns_refunds_agent.run(
                ReturnsRefundsAgentInput(
                    context=context,
                    task="assess_return",
                    item_id=request.item_id,
                    reason="damaged",
                )
            )
            pending = [request.preferred_resolution] if assessment.eligible else []
            conversation = ConversationState(
                conversation_id=state.context.conversation_id,
                identity=context.identity,
                active_order_id=request.order_id,
                pending_intents=pending,
                offered_alternatives=["refund", "store_credit", "replacement"],
                idempotency_keys=request.idempotency_keys,
                updated_at=datetime.now(UTC),
            )
            self.conversation_store.save(conversation)
            output = ConversationTurnOutput(
                final_reply=(
                    f"{request.preferred_resolution.replace('_', ' ').title()} "
                    "is eligible. No action has been taken yet; you can confirm "
                    "or change the resolution."
                    if assessment.eligible
                    else assessment.explanation
                ),
                state=conversation,
            )
            update.update(
                {
                    "resolution": assessment,
                    "conversation_state": conversation,
                    "conversation_output": output,
                    "route": "finalize",
                }
            )
            return update

        request = state.continue_request
        conversation = state.conversation_state
        if request is None or conversation is None:
            raise ValueError("Conversation continuation has no persisted state")
        key = conversation.idempotency_keys.get("store_credit")
        if key is None:
            raise ValueError("Conversation state has no store-credit idempotency key")
        resolution = self.returns_refunds_agent.run(
            ReturnsRefundsAgentInput(
                context=context,
                task="store_credit",
                item_id=request.item_id,
                reason="damaged",
                idempotency_key=key,
            )
        )
        actions = [resolution.action] if resolution.action else []
        updated_state = conversation.model_copy(
            update={
                "resolved_intents": ["store_credit"] if resolution.action else [],
                "pending_intents": [],
                "prior_actions": [*conversation.prior_actions, *actions],
                "updated_at": datetime.now(UTC),
            }
        )
        self.conversation_store.save(updated_state)
        update.update(
            {
                "resolution": resolution,
                "conversation_state": updated_state,
                "actions": actions,
                "facts": [
                    {
                        "order_id": conversation.active_order_id,
                        "selected_resolution": "store credit",
                        "policy_rechecked": True,
                        "committed": resolution.action is not None,
                        "amount": (
                            str(resolution.amount.amount)
                            if resolution.amount is not None
                            else None
                        ),
                        "replacement_created": False,
                        "reason": resolution.explanation,
                    }
                ],
                "route": "model_reply",
            }
        )
        return update

    def _account_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("account")
        request = state.multi_request
        context = state.protected_context
        if request is None or context is None:
            raise ValueError("Account node requires multi-intent request and identity")
        replacement = "replace" in request.context.customer_message.lower()
        result = self.account_agent.run(
            AccountAgentInput(
                context=context,
                task="change_shipping_address",
                new_address=request.new_address,
                idempotency_key=request.address_idempotency_key,
                replacement_context=replacement,
            )
        )
        facts = list(state.facts)
        facts.append(
            {
                "step": (
                    "change replacement address"
                    if replacement
                    else "change original order address"
                ),
                "allowed": result.changed,
                "reason": result.explanation,
            }
        )
        actions = list(state.actions)
        if result.action:
            actions.append(result.action)
        update.update(
            {
                "account_result": result,
                "facts": facts,
                "actions": actions,
                "route": (
                    "returns_refunds"
                    if replacement and result.changed
                    else "model_reply"
                ),
                "phase": "replace" if replacement else "complete",
            }
        )
        return update

    def _policy_knowledge_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("policy_knowledge")
        answer = self.policy_knowledge_agent.run(
            PolicyKnowledgeAgentInput(
                context=state.context,
                question=state.context.customer_message,
            )
        )
        update["policy_answer"] = answer
        return update

    def _verifier_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("verifier")
        answer = state.policy_answer
        if answer is None:
            raise ValueError("Verifier node has no policy answer")
        final_reply, verifier = self.verifier_agent.finalize(
            VerifierInput(
                context=state.context,
                draft_reply=answer.answer,
                citations=answer.citations,
            )
        )
        self._trace(
            state.context,
            "verification",
            "verifier",
            args={
                "approved": verifier.approved,
                "action_claims_valid": verifier.deterministic.action_claims_valid,
                "citations_valid": verifier.deterministic.citations_valid,
            },
        )
        update.update(
            {
                "verifier_result": verifier,
                "final_reply": final_reply,
                "policy_output": PolicySupervisorOutput(
                    final_reply=final_reply,
                    citations=answer.citations if verifier.approved else [],
                    grounded=answer.grounded and verifier.approved,
                    verifier=verifier,
                ),
            }
        )
        return update

    def _memory_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("memory")
        request = state.continue_request
        if request is None:
            raise ValueError("Memory node has no continuation request")
        conversation = self.conversation_store.load(state.context.conversation_id)
        if (
            conversation is None
            or conversation.identity is None
            or conversation.active_order_id is None
        ):
            raise LookupError("No verified conversation state was found")
        if "store credit" not in state.context.customer_message.lower():
            update.update(
                {
                    "conversation_state": conversation,
                    "conversation_output": ConversationTurnOutput(
                        final_reply=(
                            "Please confirm refund, replacement, or store credit."
                        ),
                        state=conversation,
                    ),
                    "route": "finalize",
                }
            )
            return update
        update.update(
            {
                "conversation_state": conversation,
                "protected_context": state.context.model_copy(
                    update={
                        "identity": conversation.identity,
                        "active_order_id": conversation.active_order_id,
                    }
                ),
                "route": "returns_refunds",
            }
        )
        return update

    def _model_reply_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("model_reply")
        if state.operation == "order_status":
            request = state.order_request
            order = state.order_details
            if request is None or order is None:
                raise ValueError("Order reply node is missing facts")
            model_request = ModelRequest(
                provider=self.settings.model_provider,
                model_id=self.settings.model_id,
                messages=[
                    ModelMessage(
                        role="system",
                        content=(
                            "Write one concise customer-service reply using only the "
                            "supplied order facts. Do not invent promises, dates, or actions."
                        ),
                    ),
                    ModelMessage(
                        role="user",
                        content=(
                            f"Customer question: {state.context.customer_message}\n"
                            "Verified order facts: "
                            f"{order.model_dump_json(exclude_none=True)}"
                        ),
                    ),
                ],
                template_version="m1-order-status-v1",
                tool_schema_version="m1-v1",
            )
        elif state.operation == "refund":
            request = state.refund_request
            if request is None:
                raise ValueError("Refund reply node has no request")
            model_request = ModelRequest(
                provider=self.settings.model_provider,
                model_id=self.settings.model_id,
                messages=[
                    ModelMessage(
                        role="system",
                        content=(
                            "Write one concise customer-service reply using only the "
                            "supplied policy facts. State an action only when "
                            "action_committed is true."
                        ),
                    ),
                    ModelMessage(
                        role="user",
                        content=(
                            f"Customer request: {state.context.customer_message}\n"
                            f"Facts: {state.facts[0]}"
                        ),
                    ),
                ],
                template_version="m2-refund-v1",
                tool_schema_version="m2-v1",
            )
        elif state.operation == "multi_intent":
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
                            f"Customer request: {state.context.customer_message}\n"
                            f"Ordered step results: {state.facts}"
                        ),
                    ),
                ],
                template_version="m3-multi-intent-v1",
                tool_schema_version="m3-v1",
            )
        else:
            model_request = ModelRequest(
                provider=self.settings.model_provider,
                model_id=self.settings.model_id,
                messages=[
                    ModelMessage(
                        role="system",
                        content=(
                            "Confirm the revised customer choice using only the facts. "
                            "Do not claim a replacement was created."
                        ),
                    ),
                    ModelMessage(
                        role="user",
                        content=(
                            f"Follow-up: {state.context.customer_message}\n"
                            f"Facts: {state.facts[0]}"
                        ),
                    ),
                ],
                template_version="m5-follow-up-v1",
                tool_schema_version="m5-v1",
            )
        response = self.replay.invoke(model_request, self.live_call)
        self._trace(
            state.context,
            "model_call",
            "supervisor",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=Decimal(str(response.usage.cost_usd)),
        )
        text = response.text
        if (
            state.operation == "refund"
            and state.facts
            and not state.facts[0].get("action_committed")
            and _UNSUPPORTED_REFUND_CLAIM.search(text)
        ):
            text = _refund_denial_reply(state.facts[0])
            self._trace(
                state.context,
                "verification",
                "output_guard",
                args={"blocked_unsupported_refund_claim": True},
            )
        update["final_reply"] = text
        if state.operation == "order_status":
            update["order_output"] = SupervisorOutput(
                intents=["order_status"],
                plan=state.plan,
                final_reply=text,
            )
        elif state.operation == "refund":
            update["refund_output"] = RefundSupervisorOutput(
                plan=state.plan,
                final_reply=text,
                resolution=state.resolution,
            )
        elif state.operation == "multi_intent":
            resolution_intent = (
                "replacement"
                if "replace" in state.context.customer_message.lower()
                else "refund"
            )
            update["multi_output"] = MultiIntentSupervisorOutput(
                intents=[resolution_intent, "address_change"],
                plan=state.plan,
                final_reply=text,
                actions=state.actions,
            )
        else:
            if state.conversation_state is None:
                raise ValueError("Conversation reply has no state")
            update["conversation_output"] = ConversationTurnOutput(
                final_reply=text,
                state=state.conversation_state,
                actions=state.actions,
            )
        return update

    def _finalize_node(self, state: AgentGraphState) -> dict[str, Any]:
        update = self._enter("finalize")
        self._trace(state.context, "agent_end", "supervisor")
        return update

    def _invoke(self, state: AgentGraphState) -> AgentGraphState:
        result = self.compiled.invoke(state.model_dump(mode="python"))
        return AgentGraphState.model_validate(result)

    def run_order_status(self, request: SupervisorInput) -> SupervisorOutput:
        state = self._invoke(
            AgentGraphState(
                operation="order_status",
                context=request.context,
                order_request=request,
            )
        )
        if state.order_output is None:
            raise RuntimeError("Order graph produced no output")
        return state.order_output

    def run_refund(self, request: RefundSupervisorInput) -> RefundSupervisorOutput:
        state = self._invoke(
            AgentGraphState(
                operation="refund",
                context=request.context,
                refund_request=request,
            )
        )
        if state.refund_output is None:
            raise RuntimeError("Refund graph produced no output")
        return state.refund_output

    def run_multi_intent(
        self, request: MultiIntentSupervisorInput
    ) -> MultiIntentSupervisorOutput:
        state = self._invoke(
            AgentGraphState(
                operation="multi_intent",
                context=request.context,
                multi_request=request,
            )
        )
        if state.multi_output is None:
            raise RuntimeError("Multi-intent graph produced no output")
        return state.multi_output

    def run_policy(self, request: PolicySupervisorInput) -> PolicySupervisorOutput:
        state = self._invoke(
            AgentGraphState(
                operation="policy",
                context=request.context,
                policy_request=request,
            )
        )
        if state.policy_output is None:
            raise RuntimeError("Policy graph produced no output")
        return state.policy_output

    def start_resolution(
        self, request: StartResolutionInput
    ) -> ConversationTurnOutput:
        state = self._invoke(
            AgentGraphState(
                operation="conversation_start",
                context=request.context,
                start_request=request,
            )
        )
        if state.conversation_output is None:
            raise RuntimeError("Conversation-start graph produced no output")
        return state.conversation_output

    def continue_conversation(
        self, request: ContinueConversationInput
    ) -> ConversationTurnOutput:
        state = self._invoke(
            AgentGraphState(
                operation="conversation_continue",
                context=request.context,
                continue_request=request,
            )
        )
        if state.conversation_output is None:
            raise RuntimeError("Conversation graph produced no output")
        return state.conversation_output

    def mermaid(self, active_node: str | None = None) -> str:
        diagram = self.compiled.get_graph().draw_mermaid()
        if active_node:
            diagram += (
                f"\nstyle {active_node} fill:#ffcc66,stroke:#9a6700,"
                "stroke-width:3px"
            )
        return diagram
