"""Progress reporting and cancellation shared by long-running operations."""

import threading
from collections.abc import Callable
from dataclasses import dataclass

from .errors import Cancelled

__all__ = ["CancelToken", "Progress", "ProgressCallback", "report"]


@dataclass(frozen=True, slots=True)
class Progress:
    task: str
    current: int
    total: int | None = None
    unit: str = "item"


ProgressCallback = Callable[[Progress], None]


class CancelToken:
    """Thread-safe flag passed as `cancel=` to stop an operation."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled("Operation cancelled")


def report(
    callback: ProgressCallback | None,
    task: str,
    current: int,
    total: int | None = None,
    unit: str = "item",
) -> None:
    if callback is not None:
        callback(Progress(task, current, total, unit))
