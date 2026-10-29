"""Audit lookup used by deterministic reply verification."""

from agentdesk.db.repository import Repository
from agentdesk.schemas.tools import LookupAuditActionsArgs, LookupAuditActionsResult


def lookup_audit_actions(
    repository: Repository, args: LookupAuditActionsArgs
) -> LookupAuditActionsResult:
    return repository.lookup_audit_actions(args.audit_ids)
