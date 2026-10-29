"""Code-first final reply verifier with one optional regeneration."""

from __future__ import annotations

import json

from agentdesk.config import Settings
from agentdesk.db.repository import Repository
from agentdesk.runtime.replay import LiveCall, ModelMessage, ModelRequest, ReplayCache
from agentdesk.schemas.agents import (
    DeterministicVerification,
    LLMReplyCheck,
    VerifierInput,
    VerifierOutput,
)
from agentdesk.schemas.tools import (
    LookupAuditActionsArgs,
    ValidateCitationsArgs,
)
from agentdesk.tools.policy_search import validate_citations
from agentdesk.tools.support import lookup_audit_actions


SAFE_FALLBACK = (
    "I can't confirm a fully supported answer right now. "
    "Please contact Northwind Goods support for review."
)


class VerifierAgent:
    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        *,
        live_call: LiveCall | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.replay = ReplayCache(settings.replay_dir, settings.llm_mode)
        self.live_call = live_call

    def deterministic_check(
        self, request: VerifierInput
    ) -> DeterministicVerification:
        audit_result = lookup_audit_actions(
            self.repository,
            LookupAuditActionsArgs(
                audit_ids=[claim.audit_id for claim in request.action_claims]
            ),
        )
        non_committed = [
            record.audit_id
            for record in audit_result.records
            if record.outcome != "committed"
        ]
        citation_result = validate_citations(
            self.settings.policies_dir,
            ValidateCitationsArgs(citations=request.citations),
        )
        errors = []
        if audit_result.missing_audit_ids:
            errors.append(
                f"Missing audit actions: {audit_result.missing_audit_ids}"
            )
        if non_committed:
            errors.append(f"Claimed actions were not committed: {non_committed}")
        if not citation_result.valid:
            errors.append("One or more policy citations do not exist.")
        return DeterministicVerification(
            action_claims_valid=(
                not audit_result.missing_audit_ids and not non_committed
            ),
            citations_valid=citation_result.valid,
            errors=errors,
        )

    def _llm_check(self, request: VerifierInput) -> LLMReplyCheck:
        model_request = ModelRequest(
            provider=self.settings.model_provider,
            model_id=self.settings.model_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Check customer-service tone and unsupported promises. "
                        "Return JSON only with this exact shape: "
                        '{"tone_ok": true, "unsupported_promises": []}. '
                        "A promise is unsupported if it claims an action, timing, "
                        "guarantee, or policy not present in the supplied evidence."
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=(
                        f"Draft: {request.draft_reply}\n"
                        f"Audited action claims: "
                        f"{[claim.description for claim in request.action_claims]}\n"
                        f"Policy evidence: "
                        f"{[citation.quote for citation in request.citations]}"
                    ),
                ),
            ],
            template_version="m4-verifier-v1",
            tool_schema_version="m4-v1",
        )
        response = self.replay.invoke(model_request, self.live_call)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.removeprefix("```json").removeprefix("```")
            raw = raw.removesuffix("```").strip()
        try:
            return LLMReplyCheck.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return LLMReplyCheck(
                tone_ok=False,
                unsupported_promises=["Verifier returned invalid JSON."],
            )

    def run(self, request: VerifierInput) -> VerifierOutput:
        deterministic = self.deterministic_check(request)
        if (
            not deterministic.action_claims_valid
            or not deterministic.citations_valid
        ):
            return VerifierOutput(
                approved=False,
                deterministic=deterministic,
                regenerate=request.regeneration_count == 0,
                safe_fallback=(
                    SAFE_FALLBACK if request.regeneration_count == 1 else None
                ),
            )
        llm_check = self._llm_check(request)
        approved = llm_check.tone_ok and not llm_check.unsupported_promises
        return VerifierOutput(
            approved=approved,
            deterministic=deterministic,
            llm_check=llm_check,
            regenerate=not approved and request.regeneration_count == 0,
            safe_fallback=(
                SAFE_FALLBACK
                if not approved and request.regeneration_count == 1
                else None
            ),
        )

    def finalize(self, request: VerifierInput) -> tuple[str, VerifierOutput]:
        first = self.run(request)
        if first.approved:
            return request.draft_reply, first
        if not first.regenerate:
            return first.safe_fallback or SAFE_FALLBACK, first

        regeneration_request = ModelRequest(
            provider=self.settings.model_provider,
            model_id=self.settings.model_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "Rewrite the reply once. Use only the supplied audited actions "
                        "and policy evidence; remove unsupported promises."
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=(
                        f"Draft: {request.draft_reply}\n"
                        f"Actions: "
                        f"{[claim.description for claim in request.action_claims]}\n"
                        f"Policies: "
                        f"{[citation.quote for citation in request.citations]}\n"
                        f"Problems: {first.deterministic.errors} "
                        f"{first.llm_check.unsupported_promises if first.llm_check else []}"
                    ),
                ),
            ],
            template_version="m4-regenerate-v1",
            tool_schema_version="m4-v1",
        )
        regenerated = self.replay.invoke(regeneration_request, self.live_call)
        second_request = request.model_copy(
            update={
                "draft_reply": regenerated.text,
                "regeneration_count": 1,
            }
        )
        second = self.run(second_request)
        if second.approved:
            return regenerated.text, second
        return second.safe_fallback or SAFE_FALLBACK, second
