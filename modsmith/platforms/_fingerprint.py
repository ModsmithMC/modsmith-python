"""CurseForge file fingerprints."""

import array
import sys
from collections.abc import Iterator
from pathlib import Path

CHUNK_SIZE = 1024 * 1024
# CurseForge ignores these bytes: tab, line feed, carriage return and space.
WHITESPACE = b"\t\n\r "
SEED = 1
MULTIPLIER = 0x5BD1E995
MASK = 0xFFFFFFFF


def _chunks(path: Path) -> Iterator[bytes]:
    """Yield a file's contents with the ignored bytes removed."""
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_SIZE):
            yield chunk.translate(None, WHITESPACE)


def fingerprint(path: Path) -> int:
    """Return a file's CurseForge fingerprint, a 32-bit MurmurHash2 variant.

    Args:
        path: The file.

    Returns:
        The fingerprint.

    Raises:
        OSError: The file could not be read.
    """
    length = sum(len(chunk) for chunk in _chunks(path))
    value = (SEED ^ length) & MASK
    tail = b""
    for chunk in _chunks(path):
        data = tail + chunk
        end = len(data) & ~3
        tail = data[end:]
        words = array.array("I")
        words.frombytes(data[:end])
        if sys.byteorder == "big":
            words.byteswap()
        for word in words:
            word = (word * MULTIPLIER) & MASK
            word ^= word >> 24
            word = (word * MULTIPLIER) & MASK
            value = ((value * MULTIPLIER) & MASK) ^ word
    if tail:
        value ^= int.from_bytes(tail, "little")
        value = (value * MULTIPLIER) & MASK
    value ^= value >> 13
    value = (value * MULTIPLIER) & MASK
    return value ^ (value >> 15)
