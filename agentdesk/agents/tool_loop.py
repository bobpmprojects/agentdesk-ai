"""A small, capped Thought -> Action -> Observation loop for tool-using agents.

The model replies with one JSON object per turn: a tool call or a final answer.
Tools are plain Python functions; their results go back to the model as an
observation. Every model call goes through the record/replay cache, so a
recorded run replays exactly, with no API key.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import Field, ValidationError

from agentdesk.config import Settings
from agentdesk.runtime.replay import LiveCall, ModelMessage, ModelRequest, ReplayCache
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.common import AgentContext, ContractModel, TraceEvent
from agentdesk.schemas.planner import AgentStep

Tool = Callable[[dict[str, Any]], dict[str, Any]]

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class LoopResult(ContractModel):
    final: dict[str, Any] | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    stop_reason: str


class ToolLoop:
    def __init__(
        self,
        *,
        agent: str,
        system_prompt: str,
        tools: dict[str, Tool],
        settings: Settings,
        trace: TraceCollector,
        template_version: str,
        live_call: LiveCall | None = None,
        max_tool_calls: int = 4,
    ) -> None:
        self.agent = agent
        self.system_prompt = system_prompt
        self.tools = tools
        self.settings = settings
        self.trace = trace
        self.template_version = template_version
        self.live_call = live_call
        self.max_tool_calls = max_tool_calls
        self.replay = ReplayCache(settings.replay_dir, settings.llm_mode)

    def run(self, context: AgentContext, task: str) -> LoopResult:
        messages = [
            ModelMessage(role="system", content=self.system_prompt),
            ModelMessage(role="user", content=task),
        ]
        steps: list[AgentStep] = []
        for turn in range(self.max_tool_calls + 1):
            request = ModelRequest(
                provider=self.settings.model_provider,
                model_id=self.settings.model_id,
                messages=messages,
                template_version=self.template_version,
                tool_schema_version=f"{self.template_version}-tools",
            )
            response = self.replay.invoke(request, self.live_call)
            action = parse_json_object(response.text)
            self._trace_model_call(context, response, action)
            if action is None:
                return LoopResult(steps=steps, stop_reason="invalid_output")
            thought = str(action.get("thought", ""))[:600]
            if isinstance(action.get("final"), dict):
                steps.append(AgentStep(agent=self.agent, thought=thought))
                return LoopResult(final=action["final"], steps=steps, stop_reason="final")
            if turn == self.max_tool_calls:
                return LoopResult(steps=steps, stop_reason="step_cap")
            tool_name = str(action.get("tool", ""))
            args = action.get("args") if isinstance(action.get("args"), dict) else {}
            observation = self._call_tool(tool_name, args)
            steps.append(
                AgentStep(
                    agent=self.agent,
                    thought=thought,
                    tool=tool_name,
                    args=args,
                    observation=observation,
                )
            )
            messages = [
                *messages,
                ModelMessage(role="assistant", content=response.text),
                ModelMessage(
                    role="user",
                    content="Observation: " + json.dumps(observation, sort_keys=True),
                ),
            ]
        return LoopResult(steps=steps, stop_reason="step_cap")

    def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {
                "error": f"Unknown tool '{name}'.",
                "available_tools": sorted(self.tools),
            }
        try:
            return tool(args)
        except (ValidationError, ValueError, KeyError) as exc:
            return {"error": f"Invalid arguments for {name}: {exc.__class__.__name__}."}

    def _trace_model_call(self, context: AgentContext, response, action) -> None:
        self.trace.add(
            TraceEvent(
                event_id=uuid4(),
                conversation_id=context.conversation_id,
                turn_id=context.turn_id,
                timestamp=datetime.now(UTC),
                event_type="model_call",
                agent=self.agent,
                tool=str(action.get("tool")) if action and action.get("tool") else None,
                args_redacted={"valid_output": action is not None},
                latency_ms=0,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=Decimal(str(response.usage.cost_usd)),
            )
        )
