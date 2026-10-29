from pathlib import Path
from uuid import uuid4

from agentdesk.agents.policy_knowledge import PolicyKnowledgeAgent
from agentdesk.agents.supervisor import Supervisor
from agentdesk.agents.verifier import SAFE_FALLBACK, VerifierAgent
from agentdesk.config import Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.runtime.replay import ModelRequest, ModelResponse
from agentdesk.schemas.agents import (
    PolicyKnowledgeAgentInput,
    PolicySupervisorInput,
    VerifierInput,
)
from agentdesk.schemas.common import ActionClaim, AgentContext, PolicyCitation


def context(message: str) -> AgentContext:
    return AgentContext(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        customer_message=message,
    )


def test_policy_agent_returns_section_citation_or_explicitly_declines() -> None:
    settings = Settings()
    agent = PolicyKnowledgeAgent(settings.policies_dir)

    covered = agent.run(
        PolicyKnowledgeAgentInput(
            context=context("What is the cash refund limit?"),
            question="What is the cash refund limit?",
        )
    )
    missing = agent.run(
        PolicyKnowledgeAgentInput(
            context=context("Do you price match competitors?"),
            question="Do you price match competitors?",
        )
    )

    assert covered.grounded is True
    assert covered.citations[0].section_id == "refund-limit"
    assert "returns-and-refunds.md#refund-limit" in covered.answer
    assert missing.insufficient_policy is True
    assert missing.citations == []
    assert "couldn't find" in missing.answer


def test_fabricated_action_and_citation_are_blocked_before_llm(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    live_calls = 0

    def live_call(_: ModelRequest) -> ModelResponse:
        nonlocal live_calls
        live_calls += 1
        return ModelResponse(
            text='{"tone_ok": true, "unsupported_promises": []}'
        )

    verifier = VerifierAgent(
        Repository(connection),
        Settings(
            database_path=database,
            replay_dir=tmp_path / "replay",
            llm_mode="record",
        ),
        live_call=live_call,
    )
    result = verifier.run(
        VerifierInput(
            context=context("test"),
            draft_reply="I issued a refund under a made-up policy.",
            action_claims=[
                ActionClaim(
                    action_type="refund",
                    audit_id=uuid4(),
                    order_id="ORD-0008",
                    description="Refund issued.",
                )
            ],
            citations=[
                PolicyCitation(
                    document="missing.md",
                    section_id="invented",
                    section_title="Invented",
                    quote="Made up.",
                )
            ],
        )
    )

    assert result.approved is False
    assert result.llm_check is None
    assert result.deterministic.action_claims_valid is False
    assert result.deterministic.citations_valid is False
    assert live_calls == 0
    connection.close()


def test_policy_supervisor_verifies_grounded_and_uncovered_answers(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)

    def approve(_: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text='{"tone_ok": true, "unsupported_promises": []}'
        )

    supervisor = Supervisor(
        Repository(connection),
        Settings(
            database_path=database,
            replay_dir=tmp_path / "replay",
            llm_mode="record",
        ),
        live_call=approve,
    )
    covered = supervisor.run_policy(
        PolicySupervisorInput(context=context("What is the cash refund limit?"))
    )
    missing = supervisor.run_policy(
        PolicySupervisorInput(context=context("Do you price match competitors?"))
    )

    assert covered.verifier.approved is True
    assert covered.grounded is True
    assert covered.citations
    assert missing.verifier.approved is True
    assert missing.grounded is False
    assert "can't make a policy claim" in missing.final_reply
    connection.close()


def test_failed_llm_check_gets_one_regeneration_then_fallback(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    responses = iter(
        [
            ModelResponse(
                text=(
                    '{"tone_ok": false, '
                    '"unsupported_promises": ["guaranteed tomorrow"]}'
                )
            ),
            ModelResponse(text="A revised but still unsupported reply."),
            ModelResponse(
                text=(
                    '{"tone_ok": false, '
                    '"unsupported_promises": ["still unsupported"]}'
                )
            ),
        ]
    )
    calls = 0

    def live_call(_: ModelRequest) -> ModelResponse:
        nonlocal calls
        calls += 1
        return next(responses)

    verifier = VerifierAgent(
        Repository(connection),
        Settings(
            database_path=database,
            replay_dir=tmp_path / "replay",
            llm_mode="record",
        ),
        live_call=live_call,
    )
    final, result = verifier.finalize(
        VerifierInput(
            context=context("When will it arrive?"),
            draft_reply="It is guaranteed tomorrow.",
        )
    )

    assert calls == 3
    assert result.approved is False
    assert result.regenerate is False
    assert final == SAFE_FALLBACK
    connection.close()
