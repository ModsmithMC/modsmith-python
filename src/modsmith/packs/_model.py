import dataclasses
import zipfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from .._support import write_atomic
from ..errors import PackError
from ..loaders import Loader, create
from ..net import Resource

Side = Literal["client", "server"]
Support = Literal["required", "optional", "unsupported"]


def safe_relative(name: str) -> str:
    """Reject archive paths that could escape the target directory."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name:
        raise PackError(f"Unsafe path in modpack: {name}")
    return path.as_posix()


@dataclass(frozen=True)
class FileRef:
    """A file identified by a platform, not yet given a download."""

    platform: str
    project_id: str
    file_id: str


@dataclass(frozen=True)
class PackEntry:
    """A file a pack needs. It is resolved once `path` and `urls` are known."""

    path: str | None = None
    urls: tuple[str, ...] = ()
    hashes: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)
    size: int | None = None
    client: Support = "required"
    server: Support = "required"
    ref: FileRef | None = None
    manual_url: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.path is not None and bool(self.urls)

    def support(self, side: Side) -> Support:
        return self.client if side == "client" else self.server

    def wanted(self, side: Side, include_optional: bool = False) -> bool:
        support = self.support(side)
        return support == "required" or (include_optional and support == "optional")

    def resource(self, root: Path) -> Resource:
        if self.path is None:
            raise PackError("Entry has no target path")
        return Resource(self.urls, root / self.path, dict(self.hashes), self.size)


@dataclass(frozen=True)
class Modpack:
    """A parsed modpack archive, independent of its format and platform."""

    format: str
    name: str
    version: str
    minecraft: str
    loader_kind: str
    loader_version: str
    entries: tuple[PackEntry, ...]
    archive: Path
    override_roots: Mapping[str, str] = field(
        default_factory=dict[str, str], hash=False
    )
    memory_mb: int | None = None

    @property
    def loader(self) -> Loader:
        return create(self.loader_kind, self.loader_version, self.minecraft)

    @property
    def unresolved(self) -> tuple[PackEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.is_resolved)

    def with_entries(self, entries: tuple[PackEntry, ...]) -> "Modpack":
        return dataclasses.replace(self, entries=entries)

    def iter_overrides(self, side: Side = "client") -> Iterator[tuple[str, bytes]]:
        """Yield `(relative_path, data)`, side-specific files last."""
        roots = [self.override_roots.get("common"), self.override_roots.get(side)]
        with zipfile.ZipFile(self.archive) as archive:
            for root in roots:
                if not root:
                    continue
                prefix = root.strip("/") + "/"
                for info in archive.infolist():
                    if info.is_dir() or not info.filename.startswith(prefix):
                        continue
                    relative = safe_relative(info.filename.removeprefix(prefix))
                    yield relative, archive.read(info)

    def extract_overrides(self, dest: Path, side: Side = "client") -> list[str]:
        """Write the override files into `dest` and return their paths."""
        written: list[str] = []
        for relative, data in self.iter_overrides(side):
            write_atomic(dest / relative, data)
            written.append(relative)
        return written
