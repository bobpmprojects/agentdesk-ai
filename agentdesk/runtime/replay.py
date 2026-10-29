"""Strict, deterministic record/replay cache for model calls."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from agentdesk.config import LLMMode
from agentdesk.schemas.common import ContractModel


class ModelMessage(ContractModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelRequest(ContractModel):
    provider: Literal["anthropic", "openai", "bedrock"]
    model_id: str
    messages: list[ModelMessage] = Field(min_length=1)
    template_version: str = "1"
    tool_schema_version: str = "1"

    def cache_key(self) -> str:
        canonical = self.model_dump_json(exclude_none=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ModelUsage(ContractModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)


class ModelResponse(ContractModel):
    text: str
    usage: ModelUsage = Field(default_factory=ModelUsage)


class ReplayFixture(ContractModel):
    request: ModelRequest
    response: ModelResponse


class ReplayMissError(LookupError):
    """Raised when strict replay cannot find an exact request fixture."""


LiveCall = Callable[[ModelRequest], ModelResponse]


class ReplayCache:
    def __init__(self, directory: Path, mode: LLMMode | str) -> None:
        self.directory = directory
        self.mode = LLMMode(mode)

    def fixture_path(self, request: ModelRequest) -> Path:
        return self.directory / f"{request.cache_key()}.json"

    def invoke(
        self, request: ModelRequest, live_call: LiveCall | None = None
    ) -> ModelResponse:
        path = self.fixture_path(request)
        if self.mode == LLMMode.REPLAY:
            if not path.is_file():
                raise ReplayMissError(
                    f"No replay fixture for request hash {request.cache_key()}"
                )
            fixture = ReplayFixture.model_validate_json(path.read_text())
            if fixture.request != request:
                raise ReplayMissError(f"Replay fixture mismatch at {path}")
            return fixture.response

        if live_call is None:
            raise ValueError("RECORD mode requires a live_call")

        response = live_call(request)
        fixture = ReplayFixture(request=request, response=response)
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(fixture.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        )
        return response
