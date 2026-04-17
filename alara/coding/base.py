"""Abstract base class for coding backends."""

from abc import ABC, abstractmethod
from typing import Callable

from alara.coding.models import CodingResult, CodingTask


class CodingBackend(ABC):
    """Interface that every coding backend must implement.

    Backends are responsible for executing a CodingTask and streaming
    incremental output back to the caller via the on_chunk callback.
    """

    @abstractmethod
    async def run(
        self,
        task: CodingTask,
        on_chunk: Callable[[str], None],
    ) -> CodingResult:
        """Execute *task*, streaming lines through *on_chunk*.

        Args:
            task:     The coding job to run.
            on_chunk: Called once per output line as the backend produces it.

        Returns:
            CodingResult with success flag, diff, and error details.
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if the backend binary / service is reachable."""
