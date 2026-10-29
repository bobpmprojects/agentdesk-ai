"""Scripted milestone demo scenarios."""

from __future__ import annotations

import argparse
from uuid import UUID

from agentdesk.agents.strands_adapter import StrandsModelClient
from agentdesk.agents.supervisor import Supervisor
from agentdesk.config import LLMMode, Settings
from agentdesk.db.connection import connect
from agentdesk.db.repository import Repository
from agentdesk.db.seed import seed_database
from agentdesk.schemas.agents import RefundSupervisorInput, SupervisorInput
from agentdesk.schemas.common import AgentContext


DEMO_CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_TURN_ID = UUID("00000000-0000-0000-0000-000000000101")


def run_m1(settings: Settings) -> str:
    seed_database(settings.database_path)
    connection = connect(settings.database_path)
    try:
        supervisor = Supervisor(
            Repository(connection),
            settings,
            live_call=(
                StrandsModelClient(settings)
                if settings.llm_mode == LLMMode.RECORD
                else None
            ),
        )
        result = supervisor.run(
            SupervisorInput(
                context=AgentContext(
                    conversation_id=DEMO_CONVERSATION_ID,
                    turn_id=DEMO_TURN_ID,
                    customer_message="Where is my order?",
                ),
                order_id="ORD-0002",
                email="customer001@northwind.test",
            )
        )
        return result.final_reply
    finally:
        connection.close()


def run_m2(settings: Settings) -> str:
    seed_database(settings.database_path)
    connection = connect(settings.database_path)
    try:
        supervisor = Supervisor(
            Repository(connection),
            settings,
            live_call=(
                StrandsModelClient(settings)
                if settings.llm_mode == LLMMode.RECORD
                else None
            ),
        )
        under_cap = supervisor.run_refund(
            RefundSupervisorInput(
                context=AgentContext(
                    conversation_id=DEMO_CONVERSATION_ID,
                    turn_id=UUID("00000000-0000-0000-0000-000000000201"),
                    customer_message=(
                        "My blender arrived damaged. Please refund it."
                    ),
                ),
                order_id="ORD-0008",
                email="customer003@northwind.test",
                item_id="ITEM-0008",
                idempotency_key=UUID("00000000-0000-0000-0000-000000002001"),
            )
        )
        over_cap = supervisor.run_refund(
            RefundSupervisorInput(
                context=AgentContext(
                    conversation_id=DEMO_CONVERSATION_ID,
                    turn_id=UUID("00000000-0000-0000-0000-000000000202"),
                    customer_message=(
                        "My $350 blender arrived damaged. Please refund it."
                    ),
                ),
                order_id="ORD-0004",
                email="customer002@northwind.test",
                item_id="ITEM-0004",
                idempotency_key=UUID("00000000-0000-0000-0000-000000002002"),
            )
        )
        return (
            f"UNDER $200: {under_cap.final_reply}\n"
            f"$350 REQUEST: {over_cap.final_reply}"
        )
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an AgentDesk milestone scenario")
    parser.add_argument("milestone", choices=["m1", "m2"])
    parser.add_argument("--mode", choices=["record", "replay"], required=True)
    args = parser.parse_args()
    settings = Settings(llm_mode=args.mode)
    if args.milestone == "m1":
        print(run_m1(settings))
    elif args.milestone == "m2":
        print(run_m2(settings))


if __name__ == "__main__":
    main()
