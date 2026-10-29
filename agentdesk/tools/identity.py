"""Identity-verification tool."""

from agentdesk.db.repository import Repository
from agentdesk.schemas.tools import VerifyIdentityArgs, VerifyIdentityResult


def verify_identity(
    repository: Repository, args: VerifyIdentityArgs
) -> VerifyIdentityResult:
    return repository.verify_identity(args.order_id, args.email.get_secret_value())
