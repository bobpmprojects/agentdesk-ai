"""Milestone smoke demo entry point."""

from agentdesk.config import Settings
from agentdesk.db.seed import seed_database
from agentdesk.retrieval import load_policy_sections
from agentdesk.runtime.replay import ModelMessage, ModelRequest, ReplayCache


def m0_request(settings: Settings) -> ModelRequest:
    return ModelRequest(
        provider=settings.model_provider,
        model_id=settings.model_id,
        messages=[
            ModelMessage(
                role="user",
                content="Reply with exactly: AgentDesk replay is ready.",
            )
        ],
        template_version="m0-v1",
        tool_schema_version="m0-v1",
    )


def main() -> None:
    settings = Settings(llm_mode="replay")
    counts = seed_database(settings.database_path)
    sections = load_policy_sections(settings.policies_dir)
    documents = {section.document for section in sections}
    response = ReplayCache(settings.replay_dir, "replay").invoke(m0_request(settings))
    print(f"Customers: {counts['customers']}")
    print(f"Orders: {counts['orders']}")
    print(f"States: {counts['order_states']}")
    print(f"Policy documents indexed: {len(documents)}")
    print(f"Replay: {response.text}")


if __name__ == "__main__":
    main()
