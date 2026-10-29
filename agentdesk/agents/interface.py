"""Framework-neutral model and agent interfaces."""

from __future__ import annotations

from typing import Protocol, TypeVar

from agentdesk.schemas.common import ContractModel

InputT_contra = TypeVar("InputT_contra", bound=ContractModel, contravariant=True)
OutputT_co = TypeVar("OutputT_co", bound=ContractModel, covariant=True)


class Agent(Protocol[InputT_contra, OutputT_co]):
    def run(self, request: InputT_contra) -> OutputT_co:
        """Run one typed agent operation."""
        ...
