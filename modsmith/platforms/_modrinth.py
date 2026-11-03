"""The Modrinth platform."""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..net import Session, file_hash
from ..net._session import DEFAULT_USER_AGENT
from ..progress import CancelToken, ProgressCallback
from ._base import (
    Dependency,
    Platform,
    Project,
    ProjectType,
    Release,
    ReleaseFile,
    SearchResults,
    SearchSort,
    category_names,
    collect_pages,
    digest_files,
    project_ref,
    release_versions,
)

API_URL = "https://api.modrinth.com/v2"
SITE_URL = "https://modrinth.com"
PAGE_SIZE = 100
SEARCH_PAGE = 100
# Ids per bulk project lookup, to keep the address short.
LOOKUP_BATCH = 100
SORT_INDEXES = {
    "relevance": "relevance",
    "downloads": "downloads",
    "popularity": "follows",
    "newest": "newest",
    "updated": "updated",
}
# Modrinth lists loaders among a search result's categories.
LOADER_TAGS = frozenset(
    {
        "babric",
        "bukkit",
        "bungeecord",
        "canvas",
        "datapack",
        "fabric",
        "folia",
        "forge",
        "iris",
        "legacy-fabric",
        "liteloader",
        "minecraft",
        "modloader",
        "neoforge",
        "nilloader",
        "optifine",
        "ornithe",
        "paper",
        "purpur",
        "quilt",
        "rift",
        "spigot",
        "sponge",
        "vanilla",
        "velocity",
        "waterfall",
    }
)
# The most hashes to send in one request.
BATCH_SIZE = 500


class _Hit(BaseModel):
    """One search result from the Modrinth API."""

    project_id: str
    slug: str
    title: str
    description: str = ""
    project_type: str = "modpack"
    icon_url: str | None = None
    downloads: int = 0
    author: str | None = None
    categories: list[str] = Field(default_factory=list[str])
    date_modified: str = ""
    follows: int | None = None
    versions: list[str] = Field(default_factory=list[str])

    def to_project(self, platform: str) -> Project:
        """Convert this result to a `Project`."""
        return Project(
            platform=platform,
            id=self.project_id,
            slug=self.slug,
            name=self.title,
            summary=self.description,
            project_type=self.project_type,
            icon_url=self.icon_url,
            url=_project_url(self.project_type, self.slug),
            downloads=self.downloads,
            author=self.author,
            categories=category_names(self.categories, LOADER_TAGS),
            updated=self.date_modified,
            follows=self.follows,
            game_versions=release_versions(self.versions),
        )


class _SearchResponse(BaseModel):
    """The Modrinth API's search response."""

    hits: list[_Hit]
    total_hits: int = 0
    offset: int = 0


class _Project(BaseModel):
    """A project from the Modrinth API."""

    id: str
    slug: str
    title: str
    description: str = ""
    project_type: str = "modpack"
    icon_url: str | None = None
    downloads: int = 0
    categories: list[str] = Field(default_factory=list[str])
    loaders: list[str] = Field(default_factory=list[str])
    updated: str = ""
    followers: int | None = None
    game_versions: list[str] = Field(default_factory=list[str])

    def to_project(self, platform: str) -> Project:
        """Convert this project to a `Project`. Modrinth gives no author name here."""
        return Project(
            platform=platform,
            id=self.id,
            slug=self.slug,
            name=self.title,
            summary=self.description,
            project_type=self.project_type,
            icon_url=self.icon_url,
            url=_project_url(self.project_type, self.slug),
            downloads=self.downloads,
            categories=category_names(self.categories, self.loaders),
            updated=self.updated,
            follows=self.followers,
            game_versions=release_versions(self.game_versions),
        )


class _File(BaseModel):
    """A version's file from the Modrinth API."""

    filename: str
    url: str
    hashes: dict[str, str] = Field(default_factory=dict[str, str])
    size: int | None = None
    primary: bool = False


class _Dependency(BaseModel):
    """A version's dependency from the Modrinth API."""

    version_id: str | None = None
    project_id: str | None = None
    dependency_type: Literal["required", "optional", "incompatible", "embedded"]


class _Version(BaseModel):
    """A version from the Modrinth API."""

    id: str
    project_id: str
    name: str
    version_type: Literal["release", "beta", "alpha"] = "release"
    date_published: str = ""
    game_versions: list[str] = Field(default_factory=list[str])
    loaders: list[str] = Field(default_factory=list[str])
    files: list[_File] = Field(default_factory=list[_File])
    dependencies: list[_Dependency] = Field(default_factory=list[_Dependency])


def _project_url(project_type: str, slug: str) -> str:
    """Return a project's web page."""
    return f"{SITE_URL}/{project_type}/{slug}"


class Modrinth(Platform):
    """Modrinth. No API key is needed.

    Args:
        user_agent: Identifies your tool. Modrinth asks every client to set one.
        session: The session to use, instead of creating one. ``user_agent`` is
            then ignored.
        base_url: The API's base URL.

    Attributes:
        base_url: The API's base URL.
    """

    name: ClassVar[str] = "modrinth"

    def __init__(
        self,
        user_agent: str | None = None,
        *,
        session: Session | None = None,
        base_url: str = API_URL,
    ) -> None:
        owned = None if session else Session(user_agent or DEFAULT_USER_AGENT)
        super().__init__(session or owned)
        self._owns_session = session is None
        self.base_url: str = base_url.rstrip("/")

    def _get(self, path: str, **params: Any) -> Any:
        """Send a GET request to the API."""
        return self.session.get_json(self.base_url + path, params=params)

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
        """Search Modrinth's catalogue.

        Modrinth serves 100 results a page; larger limits read several pages.

        Args:
            query: The search text.
            project_type: The kind of project to find.
            game_version: Only match this Minecraft version.
            loader: Only match this mod loader.
            sort: How to order the results.
            offset: How many results to skip.
            limit: The maximum number of results to return.

        Returns:
            The results.

        Raises:
            NetworkError: Modrinth could not be reached.
        """
        facets = [[f"project_type:{project_type}"]]
        if game_version:
            facets.append([f"versions:{game_version}"])
        if loader:
            facets.append([f"categories:{loader}"])

        def page(start: int, size: int) -> tuple[list[Project], int]:
            data = _SearchResponse.model_validate(
                self._get(
                    "/search",
                    query=query,
                    facets=json.dumps(facets),
                    index=SORT_INDEXES[sort],
                    offset=start,
                    limit=size,
                )
            )
            return [hit.to_project(self.name) for hit in data.hits], data.total_hits

        return collect_pages(page, offset, limit, SEARCH_PAGE)

    def get_project(
        self, ref: str | int, *, project_type: ProjectType = "modpack"
    ) -> Project:
        """Look up a project by id, slug or URL.

        Args:
            ref: The project's id, slug or web address.
            project_type: Not used, because Modrinth's ids are unique across types.

        Returns:
            The project.

        Raises:
            NetworkError: Modrinth could not be reached or does not know the project.
        """
        data = _Project.model_validate(self._get(f"/project/{project_ref(ref)}"))
        return data.to_project(self.name)

    def get_projects(
        self, ids: Iterable[str], *, project_type: ProjectType = "mod"
    ) -> dict[str, Project]:
        """Look up several projects by id or slug, in as few requests as possible.

        Args:
            ids: The projects' ids or slugs.
            project_type: Not used, because Modrinth's ids are unique across types.

        Returns:
            Each project Modrinth knows, keyed by the id or slug asked for.
            Unknown ones are left out.

        Raises:
            NetworkError: Modrinth could not be reached.
        """
        wanted = list(dict.fromkeys(ids))
        found: dict[str, Project] = {}
        for start in range(0, len(wanted), LOOKUP_BATCH):
            batch = wanted[start : start + LOOKUP_BATCH]
            for item in self._get("/projects", ids=json.dumps(batch)):
                project = _Project.model_validate(item).to_project(self.name)
                for key in (project.id, project.slug):
                    if key in batch:
                        found[key] = project
        return found

    def iter_releases(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> Iterator[Release]:
        """Yield a project's releases, newest first, reading pages as needed.

        Args:
            project: The project.
            game_version: Only list this Minecraft version.
            loader: Only list this mod loader.
            release_only: Leave out alpha and beta releases.

        Yields:
            Each release, once.

        Raises:
            NetworkError: Modrinth could not be reached.
        """
        params: dict[str, Any] = {"include_changelog": "false", "limit": PAGE_SIZE}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader:
            params["loaders"] = json.dumps([loader])
        seen: set[str] = set()
        offset = 0
        while True:
            page = self._get(f"/project/{project.id}/version", offset=offset, **params)
            # Modrinth can return short pages before the end of the list, so
            # only an empty page ends it, and the offset always moves by a page.
            if not page:
                return
            offset += PAGE_SIZE
            for item in page:
                version = _Version.model_validate(item)
                unwanted = release_only and version.version_type != "release"
                if version.id not in seen and not unwanted:
                    seen.add(version.id)
                    yield self._to_release(version)

    def _to_release(self, version: _Version) -> Release:
        """Convert a Modrinth version to a `Release`."""
        return Release(
            platform=self.name,
            id=version.id,
            project_id=version.project_id,
            name=version.name,
            release_type=version.version_type,
            published=version.date_published,
            game_versions=tuple(version.game_versions),
            loaders=tuple(version.loaders),
            files=tuple(
                ReleaseFile(
                    file.filename, (file.url,), file.hashes, file.size, file.primary
                )
                for file in version.files
            ),
            # An entry with neither id names only a file, which cannot be looked up.
            dependencies=tuple(
                Dependency(item.dependency_type, item.project_id, item.version_id)
                for item in version.dependencies
                if item.project_id or item.version_id
            ),
        )

    def get_release(self, release_id: str) -> Release:
        """Look up a release by id.

        Args:
            release_id: The version's id.

        Returns:
            The release.

        Raises:
            NetworkError: Modrinth could not be reached or does not know the id.
        """
        data = self._get(f"/version/{release_id}")
        return self._to_release(_Version.model_validate(data))

    def identify(
        self,
        paths: Iterable[Path | str],
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> dict[Path, Release]:
        """Find the releases that files came from, by their SHA-1 hashes.

        Args:
            paths: The files.
            progress: Receives an update as each file is read.
            cancel: Stops reading files.

        Returns:
            The release of each file Modrinth knows. Other files are left out.

        Raises:
            OSError: A file could not be read.
            NetworkError: Modrinth could not be reached.
            Cancelled: ``cancel`` was triggered.
        """
        groups = digest_files(paths, file_hash, progress, cancel)
        hashes = sorted(groups)
        releases: dict[Path, Release] = {}
        for start in range(0, len(hashes), BATCH_SIZE):
            found = self.session.post_json(
                f"{self.base_url}/version_files",
                json={
                    "hashes": hashes[start : start + BATCH_SIZE],
                    "algorithm": "sha1",
                },
            )
            for digest, item in found.items():
                release = self._to_release(_Version.model_validate(item))
                releases.update(dict.fromkeys(groups[digest], release))
        return releases
