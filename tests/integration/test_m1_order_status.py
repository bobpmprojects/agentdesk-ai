from pathlib import Path
from uuid import uuid4

from agentdesk.agents.supervisor import Supervisor
from agentdesk.config import Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.runtime.replay import ModelRequest, ModelResponse, ModelUsage
from agentdesk.schemas.agents import SupervisorInput
from agentdesk.schemas.common import AgentContext


def supervisor_input(
    *, order_id: str = "ORD-0002", email: str = "customer001@northwind.test"
) -> SupervisorInput:
    return SupervisorInput(
        context=AgentContext(
            conversation_id=uuid4(),
            turn_id=uuid4(),
            customer_message="Where is my order?",
        ),
        order_id=order_id,
        email=email,
    )


def test_identity_failure_stops_before_order_lookup(tmp_path: Path) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    supervisor = Supervisor(
        Repository(connection),
        Settings(database_path=database, replay_dir=tmp_path / "replay"),
    )

    result = supervisor.run(supervisor_input(email="wrong@northwind.test"))

    tools = [event.tool for event in supervisor.trace.events if event.tool]
    assert result.final_reply.startswith("I couldn't verify")
    assert tools == ["verify_identity", "verify_identity"]
    connection.close()


def test_verified_shipped_order_returns_grounded_status_and_trace(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    replay_dir = tmp_path / "replay"
    seed_database(database)
    connection = connect(database)
    live_calls = 0

    def live_call(request: ModelRequest) -> ModelResponse:
        nonlocal live_calls
        live_calls += 1
        assert '"status":"shipped"' in request.messages[-1].content
        assert "Northwind Parcel" in request.messages[-1].content
        return ModelResponse(
            text=(
                "Order ORD-0002 has shipped with Northwind Parcel "
                "(tracking ending in 0002)."
            ),
            usage=ModelUsage(input_tokens=30, output_tokens=15),
        )

    record_settings = Settings(
        database_path=database,
        replay_dir=replay_dir,
        llm_mode="record",
    )
    recorded_supervisor = Supervisor(
        Repository(connection), record_settings, live_call=live_call
    )
    recorded = recorded_supervisor.run(supervisor_input())

    replay_supervisor = Supervisor(
        Repository(connection),
        record_settings.model_copy(update={"llm_mode": "replay"}),
    )
    replayed = replay_supervisor.run(supervisor_input())

    assert live_calls == 1
    assert replayed.final_reply == recorded.final_reply
    assert "ORD-0002" in replayed.final_reply
    assert "shipped" in replayed.final_reply
    tools = [event.tool for event in replay_supervisor.trace.events if event.tool]
    assert "get_order_and_tracking" in tools
    identity_start = next(
        event
        for event in replay_supervisor.trace.events
        if event.tool == "verify_identity" and event.event_type == "tool_start"
    )
    assert identity_start.args_redacted["email"] == "[REDACTED]"
    connection.close()
