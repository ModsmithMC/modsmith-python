"""Locks that keep other processes away from files being written."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from .errors import LockedError
from .progress import CancelToken

GAME_LOCK = ".modsmith.lock"
WAIT_SECONDS = 600.0
POLL_SECONDS = 0.1


@contextmanager
def file_lock(
    path: Path, *, wait: float = WAIT_SECONDS, cancel: CancelToken | None = None
) -> Generator[None]:
    """Hold a lock across processes and threads.

    The operating system releases it if the process dies, so a crash leaves
    nothing to clean up. A thread that already holds the lock can take it again.

    Args:
        path: The lock file. It is created if needed.
        wait: How many seconds to wait for another holder. Zero fails at once.
        cancel: Stops the wait.

    Yields:
        Nothing. The lock is held until the block ends.

    Raises:
        LockedError: The lock is still held after ``wait`` seconds.
        Cancelled: ``cancel`` was triggered.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(path, is_singleton=True)
    deadline = time.monotonic() + wait
    while True:
        if cancel is not None:
            cancel.check()
        try:
            lock.acquire(blocking=False)
            break
        except Timeout:
            if time.monotonic() >= deadline:
                raise LockedError(f"{path.parent} is in use elsewhere") from None
            time.sleep(POLL_SECONDS)
    try:
        yield
    finally:
        lock.release()
