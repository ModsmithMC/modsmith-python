"""The data types and interface shared by every platform."""

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Literal, Self

from ..errors import NetworkError, PlatformError, UnsupportedError
from ..loaders._base import LOADER_FALLBACKS
from ..net import Resource, Session, download
from ..packs import Modpack
from ..progress import CancelToken, ProgressCallback, report

DependencyKind = Literal["required", "optional", "incompatible", "embedded"]
ProjectType = Literal["mod", "modpack", "resourcepack", "shader"]
ReleaseType = Literal["release", "beta", "alpha"]
SearchSort = Literal["relevance", "downloads", "popularity", "newest", "updated"]
# A release of the game such as 1.21.1 or 26.3, not a snapshot or a label.
GAME_VERSION = re.compile(r"^\d+(\.\d+)+$")
NOT_FOUND = 404
# Where the game looks for each kind of project, relative to the game directory.
PROJECT_FOLDERS: dict[ProjectType, str] = {
    "mod": "mods",
    "resourcepack": "resourcepacks",
    "shader": "shaderpacks",
}


def folder_kind(project_type: str) -> ProjectType | None:
    """Return a project type that has a folder in an instance, or None."""
    for kind in PROJECT_FOLDERS:
        if kind == project_type:
            return kind
    return None


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
        author: The author's name, or None if the platform did not say, as
            Modrinth's project lookups do not.
        categories: Its categories, as readable names such as ``Optimization``.
        updated: When it last changed, in ISO 8601 format, or empty.
        follows: How many people follow it, or None if unknown. CurseForge
            calls these favourites.
        game_versions: The game releases it supports, newest first. Snapshots
            and pre-releases are left out.
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
    author: str | None = None
    categories: tuple[str, ...] = ()
    updated: str = ""
    follows: int | None = None
    game_versions: tuple[str, ...] = ()

    @property
    def folder(self) -> str | None:
        """The folder the game loads this kind of project from, such as ``mods``.

        None for modpacks and for kinds that do not go in a game directory's
        top level, such as datapacks, which belong to a single world.
        """
        kind = folder_kind(self.project_type)
        return PROJECT_FOLDERS[kind] if kind else None


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
class Dependency:
    """Another project or release that a release relates to.

    Attributes:
        kind: How the release relates to it. ``embedded`` means the release
            already contains it.
        project_id: The project's id, or None if the platform names only a release.
        release_id: The exact release, or None if any compatible one will do.
    """

    kind: DependencyKind
    project_id: str | None = None
    release_id: str | None = None


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
        dependencies: What it needs, works with or conflicts with.
        version: The version label its author gave, such as ``0.6.0`` or
            ``mc1.21.1-0.6.0-fabric``, or None if the platform has none, as
            CurseForge does not.
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
    dependencies: tuple[Dependency, ...] = ()
    version: str | None = None

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


def release_versions(labels: Iterable[str]) -> tuple[str, ...]:
    """Keep the game releases among version labels, newest first, once each."""
    found = {label for label in labels if GAME_VERSION.match(label)}
    return tuple(
        sorted(found, key=lambda item: tuple(map(int, item.split("."))), reverse=True)
    )


def category_names(
    slugs: Iterable[str], leave_out: Iterable[str] = ()
) -> tuple[str, ...]:
    """Turn category slugs such as ``game-mechanics`` into ``Game Mechanics``."""
    skipped = set(leave_out)
    names = (slug.replace("-", " ").title() for slug in slugs if slug not in skipped)
    return tuple(dict.fromkeys(names))


def collect_pages(
    fetch: Callable[[int, int], tuple[list[Project], int]],
    offset: int,
    limit: int,
    page_size: int,
    reachable: int | None = None,
) -> SearchResults:
    """Read as many pages of search results as ``limit`` needs.

    Args:
        fetch: Reads one page from an offset and a size, and returns its
            projects and the total number of matches.
        offset: How many results to skip.
        limit: How many results to return in all.
        page_size: The most the platform returns at once.
        reachable: How deep the platform lets a search go, or None.

    Returns:
        The results.
    """
    projects: list[Project] = []
    total = 0
    while len(projects) < limit:
        start = offset + len(projects)
        size = min(page_size, limit - len(projects))
        if reachable is not None:
            size = min(size, reachable - start)
        if size <= 0:
            break
        page, total = fetch(start, size)
        projects.extend(page)
        if len(page) < size:
            break
    return SearchResults(tuple(projects), total, offset)


def project_ref(ref: str | int) -> str:
    """Reduce an id, slug or project URL to the id or slug."""
    return str(ref).rstrip("/").rsplit("/", 1)[-1]


def digest_files[T](
    paths: Iterable[Path | str],
    digest: Callable[[Path], T],
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> dict[T, list[Path]]:
    """Group files by their digest, reporting each one as it is read."""
    files = [Path(path) for path in paths]
    groups: dict[T, list[Path]] = {}
    for index, path in enumerate(files):
        if cancel is not None:
            cancel.check()
        groups.setdefault(digest(path), []).append(path)
        report(progress, "identify", index + 1, len(files), "file")
    return groups


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
        self.session: Session = session or Session()

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
        sort: SearchSort = "relevance",
        offset: int = 0,
        limit: int = 20,
    ) -> SearchResults:
        """Search the platform's catalogue.

        Args:
            query: The search text.
            project_type: The kind of project to find.
            game_version: Only match this Minecraft version.
            loader: Only match this mod loader.
            sort: How to order the results. ``popularity`` means follows on
                Modrinth and favourites on CurseForge.
            offset: How many results to skip.
            limit: The maximum number of results to return. The built-in
                platforms read as many pages as it takes.

        Returns:
            The results.

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

    def get_projects(
        self, ids: Iterable[str], *, project_type: ProjectType = "mod"
    ) -> dict[str, Project]:
        """Look up several projects by id at once.

        The built-in platforms do this in as few requests as they can. By
        default, each project is looked up on its own.

        Args:
            ids: The projects' ids.
            project_type: The kind of project, for platforms whose lookups
                need one.

        Returns:
            Each project the platform knows, keyed by the id it was asked for.
            Unknown ids are left out.

        Raises:
            NetworkError: The platform could not be reached.
        """
        found: dict[str, Project] = {}
        for project_id in dict.fromkeys(ids):
            try:
                found[project_id] = self.get_project(
                    project_id, project_type=project_type
                )
            except PlatformError:
                continue
            except NetworkError as e:
                if e.status != NOT_FOUND:
                    raise
        return found

    def get_release(self, release_id: str) -> Release:
        """Look up a release by id.

        Args:
            release_id: The release's id on this platform.

        Returns:
            The release.

        Raises:
            UnsupportedError: This platform cannot look up releases. That is the
                default.
            PlatformError: The platform does not know the release.
            NetworkError: The platform could not be reached.
        """
        raise UnsupportedError(f"{self.name} cannot look up release {release_id}")

    def authors(self, project: Project) -> tuple[str, ...]:
        """Return the names of the people behind a project, the owner first.

        Project lookups do not always say who made a project. Modrinth's give no
        author, so this asks the platform separately. Call it where the authors
        are shown, not for every project.

        Args:
            project: The project, from this platform.

        Returns:
            The names, empty if the platform names nobody. By default, the
            project's own ``author``.

        Raises:
            NetworkError: The platform could not be reached.
        """
        return (project.author,) if project.author else ()

    def changelog(self, release: Release) -> str:
        """Return what changed in a release, as plain text.

        Args:
            release: The release, from this platform.

        Returns:
            The changelog, or an empty string if the author wrote none.

        Raises:
            UnsupportedError: This platform cannot fetch changelogs. That is
                the default.
            NetworkError: The platform could not be reached.
        """
        raise UnsupportedError(f"{self.name} cannot fetch changelogs")

    def identify(
        self,
        paths: Iterable[Path | str],
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> dict[Path, Release]:
        """Find the releases that files came from, by their contents.

        Args:
            paths: The files.
            progress: Receives an update as each file is read.
            cancel: Stops reading files.

        Returns:
            The release of each file the platform knows. Other files are left
            out. By default, nothing is known.

        Raises:
            OSError: A file could not be read.
            NetworkError: The platform could not be reached.
            Cancelled: ``cancel`` was triggered.
        """
        return {}

    def latest_release(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> Release | None:
        """Return a project's newest release for a game version and loader.

        It reads only as many pages as it needs. For the Quilt loader, a Fabric
        release is used when there is no Quilt one, because Quilt loads Fabric
        mods.

        Args:
            project: The project.
            game_version: Only consider this Minecraft version.
            loader: Only consider this mod loader. None accepts any loader.
            release_only: Leave out alpha and beta releases.

        Returns:
            The release, or None if there is none.

        Raises:
            NetworkError: The platform could not be reached.
        """
        loaders = LOADER_FALLBACKS.get(loader, (loader,)) if loader else (None,)
        for item in loaders:
            releases = self.iter_releases(
                project,
                game_version=game_version,
                loader=item,
                release_only=release_only,
            )
            release = next(releases, None)
            if release is not None:
                return release
        return None

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
