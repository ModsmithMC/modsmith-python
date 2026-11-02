import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

HASH_PRIORITY = ("sha512", "sha256", "sha1", "md5")


def file_hash(path: Path, algorithm: str = "sha1") -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strongest_hash(hashes: Mapping[str, str]) -> tuple[str, str] | None:
    for algorithm in HASH_PRIORITY:
        value = hashes.get(algorithm)
        if value:
            return algorithm, value.lower()
    return None


def matches(path: Path, hashes: Mapping[str, str]) -> bool:
    expected = strongest_hash(hashes)
    return expected is None or file_hash(path, expected[0]) == expected[1]


@dataclass(frozen=True)
class Resource:
    """A file to download: where from, where to, and how to verify it."""

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
        return cls((url,), path, dict(hashes or {}), size)

    def is_present(self) -> bool:
        if not self.path.is_file():
            return False
        if self.size is not None and self.path.stat().st_size != self.size:
            return False
        return matches(self.path, self.hashes)
