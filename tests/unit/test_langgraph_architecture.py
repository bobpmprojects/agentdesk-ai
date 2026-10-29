from pathlib import Path
from uuid import uuid4

from agentdesk.agents.graph import AgentGraphState
from agentdesk.agents.supervisor import Supervisor
from agentdesk.config import ROOT_DIR, Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.schemas.agents import SupervisorInput
from agentdesk.schemas.common import AgentContext, ContractModel


def test_compiled_graph_exports_all_explicit_agent_nodes(tmp_path: Path) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    supervisor = Supervisor(
        Repository(connection),
        Settings(database_path=database),
    )

    mermaid = supervisor.mermaid(active_node="orders")

    for node in (
        "supervisor",
        "identity",
        "orders",
        "returns_refunds",
        "account",
        "policy_knowledge",
        "verifier",
        "memory",
        "model_reply",
        "finalize",
    ):
        assert f"{node}({node})" in mermaid
    assert "style orders fill:#ffcc66" in mermaid
    connection.close()


def test_order_status_runs_through_expected_graph_nodes(tmp_path: Path) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    visited: list[str] = []
    supervisor = Supervisor(
        Repository(connection),
        Settings(
            model_provider="openai",
            llm_mode="replay",
            database_path=database,
            replay_dir=ROOT_DIR / "fixtures" / "replay",
        ),
        on_node=visited.append,
    )

    result = supervisor.run(
        SupervisorInput(
            context=AgentContext(
                conversation_id=uuid4(),
                turn_id=uuid4(),
                customer_message="Where is my order?",
            ),
            order_id="ORD-0002",
            email="customer001@northwind.test",
        )
    )

    assert result.final_reply
    assert visited == [
        "supervisor",
        "identity",
        "orders",
        "model_reply",
        "finalize",
    ]
    connection.close()


def test_shared_graph_state_is_pydantic() -> None:
    assert issubclass(AgentGraphState, ContractModel)
    state = AgentGraphState(
        operation="policy",
        context=AgentContext(
            conversation_id=uuid4(),
            turn_id=uuid4(),
            customer_message="What is the refund policy?",
        ),
    )
    assert state.operation == "policy"
