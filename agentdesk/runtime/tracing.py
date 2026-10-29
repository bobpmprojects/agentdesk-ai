"""PII-safe in-memory tracing."""

from __future__ import annotations

from typing import Any

from agentdesk.schemas.common import TraceEvent

_SENSITIVE_KEYS = {
    "email",
    "line1",
    "line2",
    "postal_code",
    "tracking_number",
    "api_key",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class TraceCollector:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def add(self, event: TraceEvent) -> None:
        safe = event.model_copy(
            update={"args_redacted": redact(event.args_redacted)}
        )
        self.events.append(safe)
