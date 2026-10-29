from pathlib import Path
from uuid import uuid4

import pytest

from agentdesk.config import Settings
from agentdesk.db.seed import seed_database
from agentdesk.retrieval import load_policy_sections
from agentdesk.runtime.replay import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ReplayCache,
    ReplayMissError,
)
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.common import TraceEvent


def request() -> ModelRequest:
    return ModelRequest(
        provider="anthropic",
        model_id="test-model",
        messages=[ModelMessage(role="user", content="hello")],
    )


def test_seed_has_required_counts_and_mixed_states(tmp_path: Path) -> None:
    counts = seed_database(tmp_path / "agentdesk.db")

    assert counts["customers"] == 50
    assert counts["orders"] == 150
    assert set(counts["order_states"]) == {
        "processing",
        "shipped",
        "delivered",
        "delivered-damaged",
    }


def test_six_policy_documents_have_stable_sections() -> None:
    settings = Settings()
    sections = load_policy_sections(settings.policies_dir)

    assert len({section.document for section in sections}) == 6
    assert all(section.section_id and section.text for section in sections)


def test_record_then_replay_is_exact_and_hash_keyed(tmp_path: Path) -> None:
    calls = 0

    def live_call(_: ModelRequest) -> ModelResponse:
        nonlocal calls
        calls += 1
        return ModelResponse(text="recorded")

    recorded = ReplayCache(tmp_path, "record").invoke(request(), live_call)
    replayed = ReplayCache(tmp_path, "replay").invoke(request())

    assert calls == 1
    assert recorded == replayed
    assert (tmp_path / f"{request().cache_key()}.json").is_file()


def test_replay_never_falls_through_to_live_model(tmp_path: Path) -> None:
    called = False

    def live_call(_: ModelRequest) -> ModelResponse:
        nonlocal called
        called = True
        return ModelResponse(text="must not run")

    with pytest.raises(ReplayMissError):
        ReplayCache(tmp_path, "replay").invoke(request(), live_call)

    assert called is False


def test_provider_switch_selects_configured_model() -> None:
    settings = Settings(
        model_provider="openai",
        openai_model_id="configured-openai-model",
    )
    assert settings.model_id == "configured-openai-model"


def test_trace_redacts_pii() -> None:
    collector = TraceCollector()
    collector.add(
        TraceEvent(
            event_id=uuid4(),
            conversation_id=uuid4(),
            turn_id=uuid4(),
            timestamp="2026-10-29T12:00:00Z",
            event_type="tool_start",
            agent="identity",
            tool="verify_identity",
            args_redacted={
                "email": "customer@example.test",
                "nested": {"postal_code": "97201", "order_id": "ORD-0001"},
            },
            latency_ms=0,
        )
    )

    event = collector.events[0]
    assert event.args_redacted["email"] == "[REDACTED]"
    assert event.args_redacted["nested"]["postal_code"] == "[REDACTED]"
    assert event.args_redacted["nested"]["order_id"] == "ORD-0001"
