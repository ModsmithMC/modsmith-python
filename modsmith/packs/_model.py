"""The modpack model, which does not depend on any format or platform."""

import dataclasses
import zipfile
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Literal

from .._fs import write_atomic
from ..errors import PackError
from ..loaders import Loader, create
from ..minecraft import GameDir, install_version
from ..net import Resource, Session
from ..progress import CancelToken, ProgressCallback

# Which half of the game a file is for, and how much that side needs it.
Side = Literal["client", "server"]
Support = Literal["required", "optional", "unsupported"]


def safe_relative(name: str) -> str:
    """Reject archive paths that could escape the target directory.

    Args:
        name: The path inside a modpack.

    Returns:
        The normalized path, with forward slashes.

    Raises:
        PackError: The path is absolute or could leave the directory.
    """
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name:
        raise PackError(f"Unsafe path in modpack: {name}")
    return path.as_posix()


@dataclass(frozen=True)
class FileRef:
    """A file identified by a platform, not yet given a download.

    Attributes:
        platform: The platform's name.
        project_id: The project's id on that platform.
        file_id: The file's id on that platform.
    """

    platform: str
    project_id: str
    file_id: str


@dataclass(frozen=True)
class PackEntry:
    """A file a pack needs. It is resolved once `path` and `urls` are known.

    Attributes:
        path: Where the file goes in the instance, or None if not yet known.
        urls: Download locations, tried in order.
        hashes: Expected digests keyed by algorithm name.
        size: The expected size in bytes, or None if unknown.
        client: Whether the client needs it.
        server: Whether the server needs it.
        ref: The platform file it refers to, or None.
        manual_url: The page where a player can download it by hand, or None.
    """

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
        """Whether the entry has a path and a download."""
        return self.path is not None and bool(self.urls)

    def support(self, side: Side) -> Support:
        """Return how ``side`` treats this entry."""
        return self.client if side == "client" else self.server

    def wanted(self, side: Side, include_optional: bool = False) -> bool:
        """Return whether ``side`` should install this entry.

        Args:
            side: The side.
            include_optional: Also accept optional entries.

        Returns:
            True if the entry should be installed.
        """
        support = self.support(side)
        return support == "required" or (include_optional and support == "optional")

    def resource(self, root: Path) -> Resource:
        """Describe this entry's download.

        Args:
            root: The instance directory.

        Returns:
            The resource.

        Raises:
            PackError: The entry has no path yet.
        """
        if self.path is None:
            raise PackError("Entry has no target path")
        return Resource(self.urls, root / self.path, dict(self.hashes), self.size)


@dataclass(frozen=True)
class Modpack:
    """A parsed modpack archive, independent of its format and platform.

    Attributes:
        format: The archive format's name, such as ``mrpack``.
        name: The pack's name.
        version: The pack's version.
        minecraft: The Minecraft version it needs.
        loader_kind: The mod loader's name, or None for a vanilla pack.
        loader_version: The mod loader's version, or None for a vanilla pack.
        entries: The files it needs.
        archive: The archive it was read from.
        override_roots: Archive folders with extra files, keyed by ``common``,
            ``client`` or ``server``.
        memory_mb: The recommended memory, or None if not declared.
    """

    format: str
    name: str
    version: str
    minecraft: str
    loader_kind: str | None
    loader_version: str | None
    entries: tuple[PackEntry, ...]
    archive: Path
    override_roots: Mapping[str, str] = field(
        default_factory=dict[str, str], hash=False
    )
    memory_mb: int | None = None

    @property
    def loader(self) -> Loader | None:
        """The pack's mod loader, or None for a vanilla pack.

        Raises:
            UnsupportedError: The loader is not supported.
        """
        if self.loader_kind is None:
            return None
        return create(self.loader_kind, self.loader_version or "", self.minecraft)

    def install_game(
        self,
        game: GameDir,
        *,
        java: Path | None = None,
        cache_dir: Path | None = None,
        session: Session | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> str:
        """Install the game the pack runs on: its mod loader, or plain Minecraft.

        Args:
            game: The game directory.
            java: The Java binary for loaders that need one. Found or
                downloaded automatically if omitted.
            cache_dir: The cache directory. Defaults to the per-user cache.
            session: The session to use. A temporary one is created if omitted.
            progress: Receives updates for each stage.
            cancel: Stops the install.

        Returns:
            The version id to put in a launcher profile.

        Raises:
            UnsupportedError: The loader or the Minecraft version is not
                supported.
            NetworkError: A service could not be reached.
            DownloadError: A file could not be downloaded.
            LoaderError: The loader could not be installed.
            Cancelled: ``cancel`` was triggered.
        """
        loader = self.loader
        if loader is None:
            version = install_version(
                game, self.minecraft, session=session, progress=progress, cancel=cancel
            )
            return version.id
        return loader.install(
            game,
            java=java,
            cache_dir=cache_dir,
            session=session,
            progress=progress,
            cancel=cancel,
        )

    @property
    def unresolved(self) -> tuple[PackEntry, ...]:
        """The entries that have no download yet."""
        return tuple(entry for entry in self.entries if not entry.is_resolved)

    def with_entries(self, entries: tuple[PackEntry, ...]) -> "Modpack":
        """Return a copy of this pack with different entries."""
        return dataclasses.replace(self, entries=entries)

    def override_members(self, side: Side = "client") -> dict[str, zipfile.ZipInfo]:
        """Return the pack's override files without reading their contents.

        Args:
            side: The side to read.

        Returns:
            Each file's archive entry, keyed by its path relative to the
            instance. A side-specific file replaces a common one.

        Raises:
            PackError: A file's path is unsafe.
        """
        roots = [self.override_roots.get("common"), self.override_roots.get(side)]
        members: dict[str, zipfile.ZipInfo] = {}
        with zipfile.ZipFile(self.archive) as archive:
            for root in roots:
                if not root:
                    continue
                prefix = root.strip("/") + "/"
                for info in archive.infolist():
                    if info.is_dir() or not info.filename.startswith(prefix):
                        continue
                    relative = safe_relative(info.filename.removeprefix(prefix))
                    members[relative] = info
        return members

    def iter_override_files(
        self, side: Side = "client", only: Collection[str] | None = None
    ) -> Iterator[tuple[str, IO[bytes]]]:
        """Yield override files as open streams, so large files stay out of memory.

        Args:
            side: The side to read.
            only: The relative paths to read. Defaults to every file.

        Yields:
            Each file's path relative to the instance, and a stream of its
            contents. The stream closes when the iteration moves on.

        Raises:
            PackError: A file's path is unsafe.
        """
        members = self.override_members(side)
        with zipfile.ZipFile(self.archive) as archive:
            for relative, info in members.items():
                if only is None or relative in only:
                    with archive.open(info) as file:
                        yield relative, file

    def iter_overrides(self, side: Side = "client") -> Iterator[tuple[str, bytes]]:
        """Yield the pack's override files with their contents.

        Each file is read into memory whole. Use `iter_override_files` for
        packs with large files.

        Args:
            side: The side to read.

        Yields:
            Each file's path relative to the instance, and its contents.

        Raises:
            PackError: A file's path is unsafe.
        """
        for relative, file in self.iter_override_files(side):
            yield relative, file.read()

    def extract_overrides(self, dest: Path, side: Side = "client") -> list[str]:
        """Write the override files into ``dest`` and return their paths.

        Args:
            dest: The instance directory.
            side: The side to read.

        Returns:
            The relative paths that were written.

        Raises:
            PackError: A file's path is unsafe.
        """
        written: list[str] = []
        for relative, file in self.iter_override_files(side):
            write_atomic(dest / relative, file)
            written.append(relative)
        return written
