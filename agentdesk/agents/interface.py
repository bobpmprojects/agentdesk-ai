"""Framework-neutral model and agent interfaces."""

from __future__ import annotations

from typing import Protocol, TypeVar

from agentdesk.schemas.common import ContractModel


InputT = TypeVar("InputT", bound=ContractModel, contravariant=True)
OutputT = TypeVar("OutputT", bound=ContractModel, covariant=True)


class Agent(Protocol[InputT, OutputT]):
    def run(self, request: InputT) -> OutputT:
        """Run one typed agent operation."""
        ...
