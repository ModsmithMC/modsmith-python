from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class StepStarted:
    name: str
    index: int
    total: int


@dataclass(frozen=True)
class StepSkipped:
    name: str
    index: int
    total: int


@dataclass(frozen=True)
class StepFinished:
    name: str
    index: int
    total: int


@dataclass(frozen=True)
class Progress:
    task: str
    current: int
    total: int | None
    unit: str = "item"


@dataclass(frozen=True)
class Message:
    text: str
    level: str = "info"


Event = StepStarted | StepSkipped | StepFinished | Progress | Message
Emit = Callable[[Event], None]


def null_emit(event: Event) -> None:
    pass
