"""Deterministic, replay-backed AgentDesk quality evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from agentdesk.agents.identity import IdentityAgent
from agentdesk.agents.policy_knowledge import PolicyKnowledgeAgent
from agentdesk.agents.returns_refunds import ReturnsRefundsAgent
from agentdesk.agents.verifier import SAFE_FALLBACK, VerifierAgent
from agentdesk.config import ROOT_DIR, Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.policy.engine import PolicyCheckInput, PolicyEngine
from agentdesk.scenarios import run_m1, run_m2, run_m3, run_m4, run_m5
from agentdesk.schemas.agents import (
    IdentityAgentInput,
    PolicyKnowledgeAgentInput,
    ReturnsRefundsAgentInput,
    VerifierInput,
)
from agentdesk.schemas.common import AgentContext, ContractModel, Money
from agentdesk.schemas.tools import ValidateCitationsArgs
from agentdesk.tools.policy_search import validate_citations


class EvalCase(ContractModel):
    id: str
    scenario: Literal["m1", "m2", "m3", "m4", "m5"]
    expected_text: str


class EvalReport(ContractModel):
    cases: int = Field(ge=0)
    task_resolution: float = Field(ge=0, le=1)
    policy_violations: int = Field(ge=0)
    grounded_action_claims: float = Field(ge=0, le=1)
    citation_validity: float = Field(ge=0, le=1)
    unnecessary_escalations: int = Field(ge=0)
    replay_deterministic: bool
    failed_cases: list[str] = Field(default_factory=list)


SCENARIOS = {
    "m1": run_m1,
    "m2": run_m2,
    "m3": run_m3,
    "m4": run_m4,
    "m5": run_m5,
}


def load_eval_cases(path: Path | None = None) -> list[EvalCase]:
    case_path = path or ROOT_DIR / "fixtures" / "eval_cases" / "core.json"
    return [EvalCase.model_validate(item) for item in json.loads(case_path.read_text())]


def _policy_violations() -> int:
    engine = PolicyEngine()
    now = datetime(2026, 10, 29, tzinfo=UTC)
    base = {
        "order_total": Money(amount=Decimal(200)),
        "now": now,
    }
    expectations = [
        (
            engine.check(
                PolicyCheckInput(
                    operation="cancel",
                    identity_verified=False,
                    order_status="processing",
                    **base,
                )
            ).allowed,
            False,
        ),
        (
            engine.check(
                PolicyCheckInput(
                    operation="cancel",
                    identity_verified=True,
                    order_status="shipped",
                    **base,
                )
            ).allowed,
            False,
        ),
        (
            engine.check(
                PolicyCheckInput(
                    operation="refund",
                    identity_verified=True,
                    order_status="delivered",
                    requested_amount=Money(amount=Decimal(200)),
                    delivered_at=now - timedelta(days=30),
                    **base,
                )
            ).allowed,
            True,
        ),
        (
            engine.check(
                PolicyCheckInput(
                    operation="refund",
                    identity_verified=True,
                    order_status="delivered",
                    requested_amount=Money(amount=Decimal("200.01")),
                    delivered_at=now - timedelta(days=1),
                    **base,
                )
            ).allowed,
            False,
        ),
    ]
    return sum(actual != expected for actual, expected in expectations)


def _grounding_scores(settings: Settings) -> tuple[float, float]:
    seed_database(settings.database_path)
    connection = connect(settings.database_path)
    repository = Repository(connection)
    context = AgentContext(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        customer_message="Refund my damaged item.",
    )
    identity = IdentityAgent(repository).run(
        IdentityAgentInput(
            context=context,
            order_id="ORD-0008",
            email="customer003@northwind.test",
        )
    ).identity
    assert identity is not None
    result = ReturnsRefundsAgent(repository).run(
        ReturnsRefundsAgentInput(
            context=context.model_copy(
                update={"identity": identity, "active_order_id": "ORD-0008"}
            ),
            task="refund",
            item_id="ITEM-0008",
            reason="damaged",
            idempotency_key=uuid4(),
        )
    )
    deterministic = VerifierAgent(repository, settings).deterministic_check(
        VerifierInput(
            context=context,
            draft_reply=result.explanation,
            action_claims=[result.action] if result.action else [],
        )
    )
    policy_answer = PolicyKnowledgeAgent(settings.policies_dir).run(
        PolicyKnowledgeAgentInput(
            context=context,
            question="What is the cash refund limit?",
        )
    )
    citations = validate_citations(
        settings.policies_dir,
        ValidateCitationsArgs(citations=policy_answer.citations),
    )
    connection.close()
    return (
        1.0 if deterministic.action_claims_valid else 0.0,
        1.0 if citations.valid and policy_answer.citations else 0.0,
    )


def run_evals(settings: Settings, cases: list[EvalCase] | None = None) -> EvalReport:
    eval_cases = cases or load_eval_cases()
    failed = []
    outputs: list[str] = []
    replay_deterministic = True
    for case in eval_cases:
        first = SCENARIOS[case.scenario](settings)
        second = SCENARIOS[case.scenario](settings)
        outputs.append(first)
        if first != second:
            replay_deterministic = False
            failed.append(f"{case.id}: replay mismatch")
        if case.expected_text.lower() not in first.lower():
            failed.append(f"{case.id}: expected text missing")
    action_score, citation_score = _grounding_scores(settings)
    return EvalReport(
        cases=len(eval_cases),
        task_resolution=(len(eval_cases) - len({item.split(":")[0] for item in failed}))
        / len(eval_cases),
        policy_violations=_policy_violations(),
        grounded_action_claims=action_score,
        citation_validity=citation_score,
        unnecessary_escalations=sum(SAFE_FALLBACK in output for output in outputs),
        replay_deterministic=replay_deterministic,
        failed_cases=failed,
    )


def main() -> None:
    settings = Settings(model_provider="openai", llm_mode="replay")
    report = run_evals(settings)
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    if (
        report.policy_violations > 0
        or report.failed_cases
        or not report.replay_deterministic
        or report.grounded_action_claims < 1
        or report.citation_validity < 1
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
