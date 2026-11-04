"""Contracts for the LLM planner and the free-text agent turn."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator

from agentdesk.schemas.common import AgentContext, ContractModel
from agentdesk.schemas.tools import AddressInput

PlannerIntent = Literal["order_status", "refund", "address_change", "policy_question"]


class PlannerOutput(ContractModel):
    """What the model decided. Its vocabulary has no way to say "approve" or name an amount."""

    intents: list[PlannerIntent] = Field(default_factory=list, max_length=3)
    reason: Literal["damaged", "wrong_item", "other"] | None = None
    needs_clarification: bool = False
    clarifying_question: str | None = Field(default=None, max_length=300)
    rationale: str = Field(default="", max_length=400)

    @field_validator("intents")
    @classmethod
    def _unique(cls, intents: list[PlannerIntent]) -> list[PlannerIntent]:
        seen: list[PlannerIntent] = []
        for intent in intents:
            if intent not in seen:
                seen.append(intent)
        return seen


class CustomerTurnInput(ContractModel):
    """One free-text customer message plus the structured fields a support form collects."""

    context: AgentContext
    order_id: str | None = None
    email: SecretStr | None = None
    new_address: AddressInput | None = None


class ExecutedStep(ContractModel):
    """One step the code ran after the plan, and what the code decided."""

    intent: PlannerIntent
    outcome: Literal["completed", "denied", "answered", "needs_input", "unsupported"]
    detail: str


class AgentTurnOutput(ContractModel):
    redacted_message: str
    plan: PlannerOutput
    steps: list[ExecutedStep] = Field(default_factory=list)
    final_reply: str
