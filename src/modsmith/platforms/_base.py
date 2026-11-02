from abc import ABC, abstractmethod
from collections.abc import Mapping
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
    name: str
    urls: tuple[str, ...] = ()
    hashes: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)
    size: int | None = None
    primary: bool = True


@dataclass(frozen=True)
class Release:
    """One published version: a CurseForge File or a Modrinth Version."""

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
        for file in self.files:
            if file.primary:
                return file
        if not self.files:
            raise PlatformError(f"Release {self.name} has no files")
        return self.files[0]


@dataclass(frozen=True)
class SearchResults:
    projects: tuple[Project, ...]
    total: int
    offset: int = 0


def project_ref(ref: str | int) -> str:
    """Accept an id, a slug or a project URL."""
    return str(ref).rstrip("/").rsplit("/", 1)[-1]


class Platform(ABC):
    """A catalogue of projects. Subclass it to support another platform."""

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
        """Search the platform's catalogue."""

    @abstractmethod
    def get_project(
        self, ref: str | int, *, project_type: ProjectType = "modpack"
    ) -> Project:
        """Look up a project by id, slug or URL."""

    @abstractmethod
    def list_releases(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> list[Release]:
        """List a project's releases, newest first."""

    def resolve(self, pack: Modpack) -> Modpack:
        """Fill in downloads for entries this platform can identify."""
        return pack

    def fetch(
        self,
        release: Release,
        into: Path,
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> Path:
        """Download a release's primary file into a directory."""
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
