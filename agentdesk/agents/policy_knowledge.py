"""Policy/Knowledge specialist grounded in local Markdown sections."""

from pathlib import Path

from agentdesk.schemas.agents import (
    PolicyKnowledgeAgentInput,
    PolicyKnowledgeAgentOutput,
)
from agentdesk.schemas.tools import SearchPoliciesArgs
from agentdesk.tools.policy_search import search_policies


class PolicyKnowledgeAgent:
    def __init__(self, policies_dir: Path) -> None:
        self.policies_dir = policies_dir

    def run(
        self, request: PolicyKnowledgeAgentInput
    ) -> PolicyKnowledgeAgentOutput:
        result = search_policies(
            self.policies_dir,
            SearchPoliciesArgs(
                query=request.question,
                max_sections=request.max_sections,
            ),
        )
        if not result.hits:
            return PolicyKnowledgeAgentOutput(
                answer=(
                    "I couldn't find that answer in the Northwind Goods policy "
                    "documents, so I can't make a policy claim about it."
                ),
                citations=[],
                grounded=False,
                insufficient_policy=True,
            )
        citation = result.hits[0].citation
        answer = (
            f"{citation.quote} "
            f"[{citation.document}#{citation.section_id}]"
        )
        return PolicyKnowledgeAgentOutput(
            answer=answer,
            citations=[citation],
            grounded=True,
            insufficient_policy=False,
        )
