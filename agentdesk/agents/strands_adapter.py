"""The only module coupled to the Strands Agents SDK."""

from __future__ import annotations

from typing import Any

from strands import Agent as StrandsAgent
from strands.models import BedrockModel
from strands.models.anthropic import AnthropicModel
from strands.models.openai import OpenAIModel

from agentdesk.config import ModelProvider, Settings
from agentdesk.runtime.replay import ModelRequest, ModelResponse, ModelUsage


class StrandsModelClient:
    """Synchronous Strands-backed live model callable used only in RECORD mode."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _model(self) -> Any:
        provider = self.settings.model_provider
        if provider == ModelProvider.ANTHROPIC:
            client_args: dict[str, Any] = {}
            if self.settings.anthropic_api_key:
                client_args["api_key"] = (
                    self.settings.anthropic_api_key.get_secret_value()
                )
            return AnthropicModel(
                client_args=client_args or None,
                model_id=self.settings.anthropic_model_id,
                max_tokens=1024,
            )
        if provider == ModelProvider.OPENAI:
            client_args = {}
            if self.settings.openai_api_key:
                client_args["api_key"] = self.settings.openai_api_key.get_secret_value()
            return OpenAIModel(
                client_args=client_args or None,
                model_id=self.settings.openai_model_id,
            )
        return BedrockModel(model_id=self.settings.bedrock_model_id)

    def __call__(self, request: ModelRequest) -> ModelResponse:
        system_prompt = "\n".join(
            message.content for message in request.messages if message.role == "system"
        )
        prompt = "\n".join(
            f"{message.role.upper()}: {message.content}"
            for message in request.messages
            if message.role != "system"
        )
        agent = StrandsAgent(
            model=self._model(),
            system_prompt=system_prompt or None,
            callback_handler=None,
        )
        result = agent(prompt)
        text = "".join(
            block["text"]
            for block in result.message.get("content", [])
            if isinstance(block, dict) and "text" in block
        )
        invocation = result.metrics.latest_agent_invocation
        usage = invocation.usage if invocation else {}
        return ModelResponse(
            text=text.strip(),
            usage=ModelUsage(
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
            ),
        )
