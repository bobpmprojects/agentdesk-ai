from pathlib import Path
from uuid import uuid4

from agentdesk.agents.account import AccountAgent
from agentdesk.agents.identity import IdentityAgent
from agentdesk.agents.supervisor import Supervisor
from agentdesk.config import Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.runtime.replay import ModelRequest, ModelResponse
from agentdesk.schemas.agents import (
    AccountAgentInput,
    IdentityAgentInput,
    MultiIntentSupervisorInput,
)
from agentdesk.schemas.common import AgentContext
from agentdesk.schemas.tools import AddressInput


NEW_ADDRESS = AddressInput(
    line1="900 New Street",
    city="Seattle",
    region="WA",
    postal_code="98101",
    country_code="US",
)


def base_context(message: str, *, conversation_id=None) -> AgentContext:
    return AgentContext(
        conversation_id=conversation_id or uuid4(),
        turn_id=uuid4(),
        customer_message=message,
    )


def replacement_request() -> MultiIntentSupervisorInput:
    return MultiIntentSupervisorInput(
        context=base_context(
            "My blender arrived broken; replace it and send it to my new address."
        ),
        order_id="ORD-0008",
        email="customer003@northwind.test",
        item_id="ITEM-0008",
        new_address=NEW_ADDRESS,
        refund_idempotency_key=uuid4(),
        address_idempotency_key=uuid4(),
        replacement_idempotency_key=uuid4(),
    )


def test_replacement_plan_orders_address_before_replacement_and_limits_change(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    replay_dir = tmp_path / "replay"
    seed_database(database)
    connection = connect(database)
    repository = Repository(connection)
    settings = Settings(
        database_path=database,
        replay_dir=replay_dir,
        llm_mode="record",
    )

    result = Supervisor(
        repository,
        settings,
        live_call=lambda _: ModelResponse(text="Address changed; replacement created."),
    ).run_multi_intent(replacement_request())

    assert [step.step_id for step in result.plan] == [
        "verify",
        "assess",
        "address",
        "replace",
    ]
    assert [action.action_type for action in result.actions] == [
        "change_shipping_address",
        "replacement",
    ]

    identity_context = base_context("Change the address again")
    verified = IdentityAgent(repository).run(
        IdentityAgentInput(
            context=identity_context,
            order_id="ORD-0008",
            email="customer003@northwind.test",
        )
    )
    assert verified.identity is not None
    second = AccountAgent(repository).run(
        AccountAgentInput(
            context=identity_context.model_copy(
                update={"identity": verified.identity, "active_order_id": "ORD-0008"}
            ),
            task="change_shipping_address",
            new_address=NEW_ADDRESS,
            idempotency_key=uuid4(),
            replacement_context=True,
        )
    )

    assert second.changed is False
    assert second.policy_decision.rule_id == "one-address-change-per-order"
    connection.close()


def test_refund_continues_when_delivered_order_address_change_is_denied(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    request = MultiIntentSupervisorInput(
        context=base_context(
            "My blender arrived broken, refund it and update my shipping address"
        ),
        order_id="ORD-0008",
        email="customer003@northwind.test",
        item_id="ITEM-0008",
        new_address=NEW_ADDRESS,
        refund_idempotency_key=uuid4(),
        address_idempotency_key=uuid4(),
        replacement_idempotency_key=uuid4(),
    )
    captured: list[ModelRequest] = []

    def live_call(model_request: ModelRequest) -> ModelResponse:
        captured.append(model_request)
        return ModelResponse(text="Refund completed; address change denied.")

    result = Supervisor(
        Repository(connection),
        Settings(
            database_path=database,
            replay_dir=tmp_path / "replay",
            llm_mode="record",
        ),
        live_call=live_call,
    ).run_multi_intent(request)

    assert [action.action_type for action in result.actions] == ["refund"]
    assert "already shipped" in captured[0].messages[-1].content
    rows = connection.execute(
        "SELECT operation, outcome FROM audit_log ORDER BY created_at"
    ).fetchall()
    assert [(row["operation"], row["outcome"]) for row in rows] == [
        ("refund", "committed"),
        ("change_shipping_address", "denied"),
    ]
    connection.close()


def test_verified_customer_can_update_contact_preferences(tmp_path: Path) -> None:
    database = tmp_path / "agentdesk.db"
    seed_database(database)
    connection = connect(database)
    repository = Repository(connection)
    identity_context = base_context("Stop SMS updates")
    verified = IdentityAgent(repository).run(
        IdentityAgentInput(
            context=identity_context,
            order_id="ORD-0001",
            email="customer001@northwind.test",
        )
    )
    assert verified.identity is not None

    result = AccountAgent(repository).run(
        AccountAgentInput(
            context=identity_context.model_copy(
                update={"identity": verified.identity, "active_order_id": "ORD-0001"}
            ),
            task="update_contact_preferences",
            email_opt_in=False,
            sms_opt_in=False,
            idempotency_key=uuid4(),
        )
    )

    row = connection.execute(
        "SELECT email_opt_in, sms_opt_in FROM customers WHERE id = ?",
        (str(verified.identity.customer_id),),
    ).fetchone()
    assert result.changed is True
    assert (row["email_opt_in"], row["sms_opt_in"]) == (0, 0)
    connection.close()
