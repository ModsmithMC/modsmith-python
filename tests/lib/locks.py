"""Hold a lock from another process."""

import subprocess
import sys
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


def start_holder(path: Path) -> subprocess.Popen[str]:
    """Start a process that holds a lock until its stdin closes."""
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    return process


@contextmanager
def held_elsewhere(path: Path) -> Iterator[subprocess.Popen[str]]:
    """Keep a lock held by another process during a block."""
    process = start_holder(path)
    try:
        yield process
    finally:
        process.communicate()
