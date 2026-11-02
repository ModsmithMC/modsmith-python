"""Progress reporting and cancellation shared by long-running operations."""

import threading
from collections.abc import Callable
from dataclasses import dataclass

from .errors import Cancelled

__all__ = ["CancelToken", "Progress", "ProgressCallback", "report"]


@dataclass(frozen=True, slots=True)
class Progress:
    """One update from a long-running operation.

    Attributes:
        task: The current stage, such as ``download`` or ``libraries``.
        current: The units finished so far.
        total: The units expected, or None if unknown.
        unit: What is counted, such as ``byte``, ``file`` or ``step``.
    """

    task: str
    current: int
    total: int | None = None
    unit: str = "item"


ProgressCallback = Callable[[Progress], None]


class CancelToken:
    """Thread-safe flag that stops a long-running operation.

    Pass it as ``cancel=`` and call `cancel` from another thread. The operation
    raises `Cancelled` the next time it checks the token.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. This cannot be undone."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._event.is_set()

    def check(self) -> None:
        """Stop here if cancellation has been requested.

        Raises:
            Cancelled: Cancellation has been requested.
        """
        if self.cancelled:
            raise Cancelled("Operation cancelled")


def report(
    callback: ProgressCallback | None,
    task: str,
    current: int,
    total: int | None = None,
    unit: str = "item",
) -> None:
    """Send a `Progress` update if a callback was given.

    Args:
        callback: The callback, or None to do nothing.
        task: The current stage.
        current: The units finished so far.
        total: The units expected, or None if unknown.
        unit: What is counted.
    """
    if callback is not None:
        callback(Progress(task, current, total, unit))
