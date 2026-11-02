from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .events import Emit, StepFinished, StepSkipped, StepStarted, null_emit


class Step(Protocol):
    name: str

    def is_done(self) -> bool: ...

    def run(self, emit: Emit) -> None: ...


@dataclass
class FunctionStep:
    name: str
    action: Callable[[Emit], None]
    done: Callable[[], bool] | None = None

    def is_done(self) -> bool:
        return self.done() if self.done else False

    def run(self, emit: Emit) -> None:
        self.action(emit)


def run_steps(steps: Sequence[Step], emit: Emit = null_emit) -> None:
    total = len(steps)
    for index, step in enumerate(steps, start=1):
        if step.is_done():
            emit(StepSkipped(step.name, index, total))
            continue
        emit(StepStarted(step.name, index, total))
        step.run(emit)
        emit(StepFinished(step.name, index, total))
