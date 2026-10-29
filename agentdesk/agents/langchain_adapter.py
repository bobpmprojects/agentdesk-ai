"""LangChain model-provider adapter used only for live RECORD calls."""

from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agentdesk.config import ModelProvider, Settings
from agentdesk.runtime.replay import ModelRequest, ModelResponse, ModelUsage


class LangChainModelClient:
    """Provider-neutral synchronous model callable used only in RECORD mode."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _model(self) -> BaseChatModel:
        provider = self.settings.model_provider
        if provider == ModelProvider.ANTHROPIC:
            api_key = (
                self.settings.anthropic_api_key.get_secret_value()
                if self.settings.anthropic_api_key
                else None
            )
            return ChatAnthropic(
                model_name=self.settings.anthropic_model_id,
                max_tokens_to_sample=1024,
                api_key=api_key,
            )
        if provider == ModelProvider.OPENAI:
            api_key = (
                self.settings.openai_api_key.get_secret_value()
                if self.settings.openai_api_key
                else None
            )
            return ChatOpenAI(
                model=self.settings.openai_model_id,
                api_key=api_key,
            )
        return ChatBedrockConverse(model=self.settings.bedrock_model_id)

    def __call__(self, request: ModelRequest) -> ModelResponse:
        messages: list[SystemMessage | HumanMessage | AIMessage] = []
        for message in request.messages:
            if message.role == "system":
                messages.append(SystemMessage(content=message.content))
            elif message.role == "assistant":
                messages.append(AIMessage(content=message.content))
            else:
                messages.append(HumanMessage(content=message.content))

        result = self._model().invoke(messages)
        usage: dict[str, Any] = result.usage_metadata or {}
        return ModelResponse(
            text=result.text.strip(),
            usage=ModelUsage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
        )
