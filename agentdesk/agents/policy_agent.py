"""Policy agent: agentic retrieval over the store's written policies.

The agent's judgment: what to search for, whether the results actually answer the
question, whether to search again, and when to conclude the policies do not cover it.
Code decides afterwards whether its citations are real and what the customer reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from agentdesk.agents.tool_loop import ToolLoop
from agentdesk.config import Settings
from agentdesk.runtime.replay import LiveCall
from agentdesk.runtime.tracing import TraceCollector
from agentdesk.schemas.common import AgentContext, ContractModel, PolicyCitation
from agentdesk.schemas.planner import AgentStep
from agentdesk.schemas.tools import SearchPoliciesArgs
from agentdesk.tools.policy_search import search_policies

POLICY_SYSTEM_PROMPT = """You are the Policy agent for Northwind Goods, an online store. Answer the customer's question using ONLY the store's written policy sections, which you find with a search tool.

Reply with ONLY one JSON object per turn, no prose. Either a tool call:
{"thought": "one short sentence", "tool": "search_policies", "args": {"query": "keywords"}}
or your final answer:
{"thought": "one short sentence", "final": {"covered": true | false, "answer": "one or two sentences, only if covered", "citations": ["document#section_id", ...]}}

Tool:
- search_policies {"query": "..."}: keyword search over the policy documents; returns up to 3 sections with their id, title and text.

Rules:
- Search with your own keywords. If results do not answer the question, try different keywords once or twice.
- Only set covered to true when a returned section directly answers the question. Cite only sections you were shown.
- If no section answers it, set covered to false. Never answer from general knowledge.
- Use at most three searches."""


class PolicyAnswer(ContractModel):
    covered: bool
    answer: str = Field(default="", max_length=500)
    citations: list[str] = Field(default_factory=list, max_length=3)


class PolicyAgentResult(ContractModel):
    answer: PolicyAnswer | None
    retrieved: dict[str, PolicyCitation]
    steps: list[AgentStep]
    stop_reason: str


class PolicyAgent:
    def __init__(
        self,
        policies_dir: Path,
        settings: Settings,
        trace: TraceCollector,
        *,
        live_call: LiveCall | None = None,
    ) -> None:
        self.policies_dir = policies_dir
        self.settings = settings
        self.trace = trace
        self.live_call = live_call

    def run(self, context: AgentContext) -> PolicyAgentResult:
        retrieved: dict[str, PolicyCitation] = {}

        def search(args: dict[str, Any]) -> dict[str, Any]:
            result = search_policies(
                self.policies_dir,
                SearchPoliciesArgs(query=str(args["query"]), max_sections=3),
            )
            sections = []
            for hit in result.hits:
                citation = hit.citation
                key = f"{citation.document}#{citation.section_id}"
                retrieved[key] = citation
                sections.append(
                    {"id": key, "title": citation.section_title, "text": citation.quote}
                )
            if not sections:
                return {"sections": [], "note": "No section matched. Try different keywords."}
            return {"sections": sections}

        loop = ToolLoop(
            agent="policy_agent",
            system_prompt=POLICY_SYSTEM_PROMPT,
            tools={"search_policies": search},
            settings=self.settings,
            trace=self.trace,
            template_version="m7-policy-v1",
            live_call=self.live_call,
            max_tool_calls=3,
        )
        result = loop.run(context, f"Customer question: {context.customer_message}")
        answer = None
        if result.final is not None:
            try:
                answer = PolicyAnswer.model_validate(result.final)
            except ValueError:
                answer = None
        return PolicyAgentResult(
            answer=answer,
            retrieved=retrieved,
            steps=result.steps,
            stop_reason=result.stop_reason if answer else "invalid_answer",
        )
