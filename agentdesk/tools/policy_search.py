"""Local policy search and citation validation tools."""

from pathlib import Path

from agentdesk.retrieval.bm25 import BM25Index
from agentdesk.retrieval.documents import load_policy_sections
from agentdesk.schemas.common import PolicyCitation
from agentdesk.schemas.tools import (
    PolicySearchHit,
    SearchPoliciesArgs,
    SearchPoliciesResult,
    ValidateCitationsArgs,
    ValidateCitationsResult,
)


def search_policies(
    policies_dir: Path, args: SearchPoliciesArgs
) -> SearchPoliciesResult:
    sections = load_policy_sections(policies_dir)
    matches = BM25Index(sections).search(args.query, limit=args.max_sections)
    return SearchPoliciesResult(
        hits=[
            PolicySearchHit(
                citation=PolicyCitation(
                    document=section.document,
                    section_id=section.section_id,
                    section_title=section.title,
                    quote=section.text,
                ),
                score=score,
            )
            for section, score in matches
        ]
    )


def validate_citations(
    policies_dir: Path, args: ValidateCitationsArgs
) -> ValidateCitationsResult:
    sections = {
        (section.document, section.section_id): section
        for section in load_policy_sections(policies_dir)
    }
    invalid = []
    for citation in args.citations:
        section = sections.get((citation.document, citation.section_id))
        if (
            section is None
            or citation.section_title != section.title
            or citation.quote not in section.text
        ):
            invalid.append(citation)
    return ValidateCitationsResult(valid=not invalid, invalid_citations=invalid)
