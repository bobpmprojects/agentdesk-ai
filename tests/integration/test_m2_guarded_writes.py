from pathlib import Path
from uuid import uuid4

import pytest

from agentdesk.agents.identity import IdentityAgent
from agentdesk.agents.orders import OrdersAgent
from agentdesk.agents.returns_refunds import ReturnsRefundsAgent
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.schemas.agents import (
    IdentityAgentInput,
    OrdersAgentInput,
    ReturnsRefundsAgentInput,
)
from agentdesk.schemas.common import AgentContext


def context(message: str = "My item arrived damaged") -> AgentContext:
    return AgentContext(
        conversation_id=uuid4(),
        turn_id=uuid4(),
        customer_message=message,
    )


def verified_context(repository: Repository, order_id: str, email: str) -> AgentContext:
    base = context()
    verified = IdentityAgent(repository).run(
        IdentityAgentInput(context=base, order_id=order_id, email=email)
    )
    assert verified.identity is not None
    return base.model_copy(
        update={"identity": verified.identity, "active_order_id": order_id}
    )


def test_same_refund_twice_does_not_double_refund(tmp_path: Path) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    repository = Repository(connection)
    agent = ReturnsRefundsAgent(repository)
    protected = verified_context(
        repository, "ORD-0008", "customer003@northwind.test"
    )
    key = uuid4()
    request = ReturnsRefundsAgentInput(
        context=protected,
        task="refund",
        item_id="ITEM-0008",
        reason="damaged",
        idempotency_key=key,
    )

    first = agent.run(request)
    second = agent.run(request)

    assert first.action is not None
    assert second.action is not None
    assert first.action.audit_id == second.action.audit_id
    assert connection.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1
    connection.close()


def test_no_write_happens_without_identity_verification(tmp_path: Path) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    agent = ReturnsRefundsAgent(Repository(connection))
    request = ReturnsRefundsAgentInput(
        context=context(),
        task="refund",
        item_id="ITEM-0008",
        reason="damaged",
        idempotency_key=uuid4(),
    )

    with pytest.raises(PermissionError, match="Identity"):
        agent.run(request)

    assert connection.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
    connection.close()


def test_over_cap_refund_is_denied_and_store_credit_is_offered(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    repository = Repository(connection)
    protected = verified_context(
        repository, "ORD-0004", "customer002@northwind.test"
    )

    result = ReturnsRefundsAgent(repository).run(
        ReturnsRefundsAgentInput(
            context=protected,
            task="refund",
            item_id="ITEM-0004",
            reason="damaged",
            idempotency_key=uuid4(),
        )
    )

    assert result.eligible is False
    assert result.resolution == "denied"
    assert result.policy_decision.alternative == "Offer store credit."
    assert connection.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 0
    assert (
        connection.execute("SELECT outcome FROM audit_log").fetchone()["outcome"]
        == "denied"
    )
    connection.close()


def test_cancel_only_before_shipment(tmp_path: Path) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    repository = Repository(connection)
    processing = verified_context(
        repository, "ORD-0001", "customer001@northwind.test"
    )
    shipped = verified_context(
        repository, "ORD-0002", "customer001@northwind.test"
    )
    agent = OrdersAgent(repository)

    allowed = agent.run(
        OrdersAgentInput(
            context=processing,
            task="cancel",
            idempotency_key=uuid4(),
        )
    )
    denied = agent.run(
        OrdersAgentInput(
            context=shipped,
            task="cancel",
            idempotency_key=uuid4(),
        )
    )

    assert allowed.status == "cancelled"
    assert allowed.action is not None
    assert denied.status == "shipped"
    assert denied.action is None
    assert denied.policy_decision is not None
    assert denied.policy_decision.alternative == "Request a return after delivery."
    connection.close()
