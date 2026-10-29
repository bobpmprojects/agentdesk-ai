"""Stable section parser for the Markdown policy corpus."""

from __future__ import annotations

import re
from pathlib import Path

from agentdesk.schemas.common import ContractModel

SECTION_HEADING = re.compile(r"^##\s+(.+?)\s+\{#([a-z0-9-]+)\}\s*$")


class PolicySection(ContractModel):
    document: str
    section_id: str
    title: str
    text: str


def load_policy_sections(directory: Path) -> list[PolicySection]:
    sections: list[PolicySection] = []
    for path in sorted(directory.glob("*.md")):
        current_title: str | None = None
        current_id: str | None = None
        body: list[str] = []
        for line in path.read_text().splitlines():
            match = SECTION_HEADING.match(line)
            if match:
                if current_id is not None:
                    sections.append(
                        PolicySection(
                            document=path.name,
                            section_id=current_id,
                            title=current_title or current_id,
                            text="\n".join(body).strip(),
                        )
                    )
                current_title, current_id = match.groups()
                body = []
            elif current_id is not None:
                body.append(line)
        if current_id is not None:
            sections.append(
                PolicySection(
                    document=path.name,
                    section_id=current_id,
                    title=current_title or current_id,
                    text="\n".join(body).strip(),
                )
            )
    return sections
