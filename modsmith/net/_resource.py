"""Download targets and hash checks."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

HASH_PRIORITY = ("sha512", "sha256", "sha1", "md5")


def file_hash(path: Path, algorithm: str = "sha1") -> str:
    """Hash a file without loading it all into memory.

    Args:
        path: The file.
        algorithm: A name that `hashlib.new` accepts.

    Returns:
        The hexadecimal digest.
    """
    with Path(path).open("rb") as file:
        return stream_hash(file, algorithm)


def stream_hash(file: IO[bytes], algorithm: str = "sha1") -> str:
    """Hash an open file without loading it all into memory.

    Args:
        file: The open file.
        algorithm: A name that `hashlib.new` accepts.

    Returns:
        The hexadecimal digest.
    """
    digest = hashlib.new(algorithm)
    for chunk in iter(lambda: file.read(1 << 20), b""):
        digest.update(chunk)
    return digest.hexdigest()


def strongest_hash(hashes: Mapping[str, str]) -> tuple[str, str] | None:
    """Pick the strongest known hash.

    Args:
        hashes: Digests keyed by algorithm name.

    Returns:
        The algorithm and its lowercase digest, or None if none is known.
    """
    for algorithm in HASH_PRIORITY:
        value = hashes.get(algorithm)
        if value:
            return algorithm, value.lower()
    return None


def matches(path: Path, hashes: Mapping[str, str]) -> bool:
    """Check a file against its strongest hash.

    Args:
        path: The file.
        hashes: Digests keyed by algorithm name.

    Returns:
        True if the digest matches, or if no known hash was given.
    """
    expected = strongest_hash(hashes)
    return expected is None or file_hash(path, expected[0]) == expected[1]


@dataclass(frozen=True)
class Resource:
    """A file to download: where from, where to, and how to verify it.

    Attributes:
        urls: Download locations, tried in order.
        path: The destination.
        hashes: Expected digests keyed by algorithm name.
        size: The expected size in bytes, or None if unknown.
    """

    urls: tuple[str, ...]
    path: Path
    hashes: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)
    size: int | None = None

    @classmethod
    def of(
        cls,
        url: str,
        path: Path,
        hashes: Mapping[str, str] | None = None,
        size: int | None = None,
    ) -> "Resource":
        """Create a resource with one URL.

        Args:
            url: The download location.
            path: The destination.
            hashes: Expected digests keyed by algorithm name.
            size: The expected size in bytes, or None if unknown.

        Returns:
            The resource.
        """
        return cls((url,), path, dict(hashes or {}), size)

    def is_present(self) -> bool:
        """Return whether the destination already passes the size and hash checks.

        With no size or hashes to check, any existing file counts as present.
        """
        if not self.path.is_file():
            return False
        if self.size is not None and self.path.stat().st_size != self.size:
            return False
        return matches(self.path, self.hashes)
