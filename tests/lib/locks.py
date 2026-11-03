"""Hold a lock from another process."""

import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

HOLDER = """
import sys
from pathlib import Path
from modsmith._locks import file_lock

with file_lock(Path(sys.argv[1])):
    print("ready", flush=True)
    sys.stdin.read()
"""


class Holder:
    """A process that holds a lock until it is released."""

    def __init__(self, path: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert self.process.stdout is not None
        assert self.process.stdout.readline().strip() == "ready"
        self._released = threading.Lock()

    def release(self) -> None:
        """Let the process release the lock and exit.

        Safe to call from a timer thread and again from the test, because
        only one caller closes the pipes.
        """
        if not self._released.acquire(blocking=False):
            return
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.close()
        self.process.wait()
        self.process.stdout.close()

    def release_later(self, delay: float) -> None:
        """Release the lock from another thread after ``delay`` seconds."""
        threading.Timer(delay, self.release).start()


@contextmanager
def held_elsewhere(path: Path) -> Iterator[Holder]:
    """Keep a lock held by another process during a block."""
    holder = Holder(path)
    try:
        yield holder
    finally:
        holder.release()
