"""Framework-neutral Supervisor facade backed by an explicit LangGraph."""

from __future__ import annotations

from collections.abc import Callable

from agentdesk.agents.graph import AgentDeskGraph
from agentdesk.config import Settings
from agentdesk.db.repository import Repository
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
