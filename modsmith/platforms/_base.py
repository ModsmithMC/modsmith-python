"""The data types and interface shared by every platform."""

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Literal, Self

from ..errors import PlatformError
from ..net import Resource, Session, download
from ..packs import Modpack
from ..progress import CancelToken, ProgressCallback

ProjectType = Literal["mod", "modpack", "resourcepack", "shader"]
ReleaseType = Literal["release", "beta", "alpha"]


@dataclass(frozen=True)
class Project:
    """A mod, modpack or other project on a platform.

    Attributes:
        platform: The platform's name.
        id: The project's id on that platform.
        slug: The project's short name.
        name: The display name.
        summary: A short description.
        project_type: The kind of project, such as ``modpack``.
        icon_url: The icon's URL, or None.
        url: The project's web page, or None.
        downloads: The number of downloads.
    """

    platform: str
    id: str
    slug: str
    name: str
    summary: str = ""
    project_type: str = "modpack"
    icon_url: str | None = None
    url: str | None = None
    downloads: int = 0


@dataclass(frozen=True)
class ReleaseFile:
    """One file of a release.

    Attributes:
        name: The file name.
        urls: Download locations. Empty if the file cannot be downloaded directly.
        hashes: Expected digests keyed by algorithm name.
        size: The size in bytes, or None if unknown.
        primary: Whether this is the release's main file.
    """

    name: str
    urls: tuple[str, ...] = ()
    hashes: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)
    size: int | None = None
    primary: bool = True


@dataclass(frozen=True)
class Release:
    """One published version: a CurseForge File or a Modrinth Version.

    Attributes:
        platform: The platform's name.
        id: The release's id on that platform.
        project_id: The project's id on that platform.
        name: The display name.
        release_type: One of ``release``, ``beta`` or ``alpha``.
        published: The publication time, in ISO 8601 format.
        game_versions: The Minecraft versions it supports.
        loaders: The mod loaders it supports.
        files: The files it contains.
    """

    platform: str
    id: str
    project_id: str
    name: str
    release_type: ReleaseType = "release"
    published: str = ""
    game_versions: tuple[str, ...] = ()
    loaders: tuple[str, ...] = ()
    files: tuple[ReleaseFile, ...] = ()

    @property
    def primary_file(self) -> ReleaseFile:
        """The file marked as primary, or the first file.

        Raises:
            PlatformError: The release has no files.
        """
        for file in self.files:
            if file.primary:
                return file
        if not self.files:
            raise PlatformError(f"Release {self.name} has no files")
        return self.files[0]


@dataclass(frozen=True)
class SearchResults:
    """One page of search results.

    Attributes:
        projects: The projects on this page.
        total: The number of matches across all pages.
        offset: The position of this page's first project.
    """

    projects: tuple[Project, ...]
    total: int
    offset: int = 0


def project_ref(ref: str | int) -> str:
    """Reduce an id, slug or project URL to the id or slug."""
    return str(ref).rstrip("/").rsplit("/", 1)[-1]


class Platform(ABC):
    """A catalogue of projects. Subclass it to support another platform.

    Use it as a context manager, or call `close` when you are done.

    Args:
        session: The session to use. If omitted, the platform creates its own and
            closes it in `close`.

    Attributes:
        name: The platform's name.
        session: The session in use.
    """

    name: ClassVar[str]

    def __init__(self, session: Session | None = None) -> None:
        self._owns_session = session is None
        self.session = session or Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the session, if the platform created it."""
        if self._owns_session:
            self.session.close()

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        project_type: ProjectType = "modpack",
        game_version: str | None = None,
        loader: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> SearchResults:
        """Search the platform's catalogue.

        Args:
            query: The search text.
            project_type: The kind of project to find.
            game_version: Only match this Minecraft version.
            loader: Only match this mod loader.
            offset: How many results to skip.
            limit: The maximum number of results to return.

        Returns:
            One page of results.

        Raises:
            NetworkError: The platform could not be reached.
        """

    @abstractmethod
    def get_project(
        self, ref: str | int, *, project_type: ProjectType = "modpack"
    ) -> Project:
        """Look up a project by id, slug or URL.

        Args:
            ref: The project's id, slug or web address.
            project_type: The kind of project.

        Returns:
            The project.

        Raises:
            NetworkError: The platform failed or does not know the project.
        """

    @abstractmethod
    def iter_releases(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> Iterator[Release]:
        """Yield a project's releases, newest first, reading pages as needed.

        Stopping early saves requests, so ``next()`` finds the latest release
        with a single request. Use it while the platform is still open.

        Args:
            project: The project.
            game_version: Only list this Minecraft version.
            loader: Only list this mod loader.
            release_only: Leave out alpha and beta releases.

        Yields:
            Each release, once.

        Raises:
            NetworkError: The platform could not be reached.
        """

    def list_releases(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> list[Release]:
        """List all of a project's releases, newest first.

        This reads every page. Use `iter_releases` if you need only some.

        Args:
            project: The project.
            game_version: Only list this Minecraft version.
            loader: Only list this mod loader.
            release_only: Leave out alpha and beta releases.

        Returns:
            The releases.

        Raises:
            NetworkError: The platform could not be reached.
        """
        releases = self.iter_releases(
            project,
            game_version=game_version,
            loader=loader,
            release_only=release_only,
        )
        return sorted(releases, key=lambda item: item.published, reverse=True)

    def resolve(self, pack: Modpack) -> Modpack:
        """Fill in downloads for entries this platform can identify.

        Args:
            pack: The modpack.

        Returns:
            The modpack with resolved entries. By default, it is returned unchanged.
        """
        return pack

    def fetch(
        self,
        release: Release,
        into: Path,
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> Path:
        """Download a release's primary file into a directory.

        Args:
            release: The release.
            into: The directory. It is created if needed.
            progress: Receives download updates.
            cancel: Stops the download.

        Returns:
            The downloaded file.

        Raises:
            PlatformError: The file has no download link.
            DownloadError: The download failed.
            Cancelled: ``cancel`` was triggered.
        """
        file = release.primary_file
        if not file.urls:
            raise PlatformError(f"{file.name} has no download link")
        path = Path(into) / file.name
        download(
            Resource(file.urls, path, dict(file.hashes), file.size),
            session=self.session,
            progress=progress,
            cancel=cancel,
            task="fetch",
        )
        return path
