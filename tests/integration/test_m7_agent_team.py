"""M7: three agents propose, deterministic code decides.

Each test forces an agent to misbehave and checks that code still holds the line.
None of these depend on the model behaving well.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from agentdesk.agent_cases import _settings
from agentdesk.agents.graph import claims_unwritten_refund
from agentdesk.agents.policy_agent import PolicyAgentResult, PolicyAnswer
from agentdesk.agents.resolution_agent import ResolutionProposal, ResolutionResult
from agentdesk.agents.supervisor import Supervisor
from agentdesk.agents.team import NOT_COVERED_REPLY
from agentdesk.agents.tool_loop import ToolLoop
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.policy.engine import DEMO_STORE_NOW, store_clock
from agentdesk.runtime.replay import ModelResponse
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.common import AgentContext
from agentdesk.schemas.planner import CustomerTurnInput

OVER_CAP = "My $350 blender arrived broken. Refund it please."


@pytest.fixture
def team(tmp_path: Path):
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    supervisor = Supervisor(Repository(connection), _settings("replay", database))
    yield supervisor, connection
    connection.close()


def ask(supervisor: Supervisor, message: str, order_id=None, email=None):
    return supervisor.handle_message(
        CustomerTurnInput(
            context=AgentContext(
                conversation_id=uuid4(), turn_id=uuid4(), customer_message=message
            ),
            order_id=order_id,
            email=SecretStr(email) if email else None,
        )
    )


def refunds(connection, order_id: str, kind: str) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM refunds WHERE order_id = ? AND kind = ?", (order_id, kind)
    ).fetchone()[0]


def stub_writer(supervisor: Supervisor, text: str = "Here is an update on your request.") -> None:
    """These tests target code decisions, not wording, so the reply writer is stubbed."""
    original = supervisor.team.replay.invoke
    supervisor.team.replay.invoke = lambda request, live=None: (
        ModelResponse(text=text)
        if request.template_version == "m7-reply-v1"
        else original(request, live)
    )


def fake_resolution(proposal: ResolutionProposal):
    return lambda *args, **kwargs: ResolutionResult(
        proposal=proposal, steps=[], stop_reason="final"
    )


def test_code_denies_a_refund_the_agent_wrongly_approves(team) -> None:
    supervisor, connection = team
    supervisor.team.resolution.run = fake_resolution(ResolutionProposal(execute="refund"))
    stub_writer(supervisor)
    out = ask(supervisor, OVER_CAP, "ORD-0004", "customer002@northwind.test")
    assert out.steps[-1].outcome == "denied"
    assert "refund-cap-200" in out.steps[-1].detail
    assert any("write-time policy check denied" in c for c in out.code_checks)
    assert refunds(connection, "ORD-0004", "cash") == 0


def test_agent_cannot_execute_what_the_customer_did_not_ask_for(team) -> None:
    supervisor, connection = team
    supervisor.team.resolution.run = fake_resolution(ResolutionProposal(execute="store_credit"))
    stub_writer(supervisor)
    out = ask(supervisor, OVER_CAP, "ORD-0004", "customer002@northwind.test")
    assert any("turned it into an offer" in c for c in out.code_checks)
    assert "Offered: store_credit" in out.steps[-1].detail
    assert refunds(connection, "ORD-0004", "store_credit") == 0


def test_code_drops_an_offer_the_policy_does_not_allow(team) -> None:
    supervisor, _ = team
    supervisor.team.resolution.run = fake_resolution(ResolutionProposal(offer=["store_credit"]))
    stub_writer(supervisor)
    out = ask(supervisor, OVER_CAP, "ORD-0002", "customer001@northwind.test")
    assert any("Dropped offer of store_credit" in c for c in out.code_checks)
    assert "Offered" not in out.steps[-1].detail


def test_policy_answer_citing_an_unseen_section_is_blocked(team) -> None:
    supervisor, _ = team
    supervisor.team.policy_agent.run = lambda *a, **k: PolicyAgentResult(
        answer=PolicyAnswer(covered=True, answer="We price match.", citations=["pricing.md#match"]),
        retrieved={},
        steps=[],
        stop_reason="final",
    )
    out = ask(supervisor, "Do you price match competitors?")
    assert out.final_reply == NOT_COVERED_REPLY
    assert any("Policy answer blocked" in c for c in out.code_checks)


@pytest.mark.parametrize(
    ("writer_text", "check"),
    [
        ("Good news: your refund has been processed.", "Reply claimed a refund"),
        ("I can offer you store credit of $500 instead.", "amounts not in the facts"),
    ],
)
def test_reply_check_replaces_unsupported_writer_text(team, writer_text, check) -> None:
    supervisor, _ = team
    stub_writer(supervisor, writer_text)
    out = ask(supervisor, OVER_CAP, "ORD-0004", "customer002@northwind.test")
    assert any(check in c for c in out.code_checks)
    assert out.final_reply.startswith("I can't approve this cash refund")


def test_agent_loop_stops_at_the_step_cap(tmp_path: Path) -> None:
    settings = _settings("record", tmp_path / "unused.db").model_copy(
        update={"replay_dir": tmp_path / "replay"}
    )
    loop = ToolLoop(
        agent="looping_agent",
        system_prompt="test",
        tools={"ping": lambda args: {"pong": True}},
        settings=settings,
        trace=TraceCollector(),
        template_version="test-loop",
        live_call=lambda request: ModelResponse(
            text=f'{{"thought": "again {len(request.messages)}", "tool": "ping", "args": {{}}}}'
        ),
        max_tool_calls=3,
    )
    result = loop.run(
        AgentContext(conversation_id=uuid4(), turn_id=uuid4(), customer_message="x"), "go"
    )
    assert result.stop_reason == "step_cap"
    assert len(result.steps) == 3


def test_refund_claim_check_understands_negation() -> None:
    assert claims_unwritten_refund("Your refund has been processed.")
    assert not claims_unwritten_refund("Nothing has been refunded at this point.")
    assert not claims_unwritten_refund("I wasn't able to process the cash refund.")


def test_store_clock_is_pinned_unless_overridden(monkeypatch) -> None:
    monkeypatch.delenv("AGENTDESK_NOW", raising=False)
    assert store_clock() == DEMO_STORE_NOW
    monkeypatch.setenv("AGENTDESK_NOW", "2026-12-31T00:00:00+00:00")
    assert store_clock().year == 2026 and store_clock().month == 12
