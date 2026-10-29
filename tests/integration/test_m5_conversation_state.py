from pathlib import Path
from uuid import UUID, uuid4

from agentdesk.agents.supervisor import Supervisor
from agentdesk.config import Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.runtime.replay import ModelResponse
from agentdesk.schemas.agents import (
    ContinueConversationInput,
    StartResolutionInput,
)
from agentdesk.schemas.common import AgentContext


def test_follow_up_replans_to_store_credit_without_replacement(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    conversation_id = uuid4()
    connection = connect(database)
    settings = Settings(
        database_path=database,
        replay_dir=tmp_path / "replay",
        llm_mode="record",
    )
    first_supervisor = Supervisor(Repository(connection), settings)
    first = first_supervisor.start_resolution(
        StartResolutionInput(
            context=AgentContext(
                conversation_id=conversation_id,
                turn_id=uuid4(),
                customer_message="Please replace my damaged blender.",
            ),
            order_id="ORD-0008",
            email="customer003@northwind.test",
            item_id="ITEM-0008",
            preferred_resolution="replacement",
            idempotency_keys={
                "replacement": UUID("00000000-0000-0000-0000-000000005001"),
                "store_credit": UUID("00000000-0000-0000-0000-000000005002"),
            },
        )
    )

    assert first.actions == []
    assert first.state.pending_intents == ["replacement"]
    assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
    stored_json = connection.execute(
        "SELECT state_json FROM conversation_state WHERE conversation_id = ?",
        (str(conversation_id),),
    ).fetchone()["state_json"]
    assert "customer003@northwind.test" not in stored_json

    second_supervisor = Supervisor(
        Repository(connection),
        settings,
        live_call=lambda _: ModelResponse(
            text="Your revised choice is confirmed: $149 in store credit."
        ),
    )
    second = second_supervisor.continue_conversation(
        ContinueConversationInput(
            context=AgentContext(
                conversation_id=conversation_id,
                turn_id=uuid4(),
                customer_message="Actually, make it store credit.",
            ),
            item_id="ITEM-0008",
        )
    )

    assert [action.action_type for action in second.actions] == ["store_credit"]
    assert second.state.pending_intents == []
    assert second.state.resolved_intents == ["store_credit"]
    audits = connection.execute(
        "SELECT operation, outcome, policy_decision_id FROM audit_log"
    ).fetchall()
    assert [(row["operation"], row["outcome"]) for row in audits] == [
        ("store_credit", "committed")
    ]
    assert audits[0]["policy_decision_id"]
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM refunds WHERE kind = 'store_credit'"
        ).fetchone()[0]
        == 1
    )
    connection.close()
