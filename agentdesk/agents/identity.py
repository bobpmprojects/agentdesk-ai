"""Identity specialist."""

from agentdesk.db.repository import Repository
from agentdesk.schemas.agents import IdentityAgentInput, IdentityAgentOutput
from agentdesk.schemas.tools import VerifyIdentityArgs
from agentdesk.tools.identity import verify_identity


class IdentityAgent:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def run(self, request: IdentityAgentInput) -> IdentityAgentOutput:
        result = verify_identity(
            self.repository,
            VerifyIdentityArgs(order_id=request.order_id, email=request.email),
        )
        if not result.verified:
            return IdentityAgentOutput(verified=False, failure_reason="no_match")
        return IdentityAgentOutput(verified=True, identity=result.identity)
