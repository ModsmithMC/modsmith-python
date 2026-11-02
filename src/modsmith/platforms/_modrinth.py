import json
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ..net import Session
from ..net._session import DEFAULT_USER_AGENT
from ._base import (
    Platform,
    Project,
    ProjectType,
    Release,
    ReleaseFile,
    SearchResults,
    project_ref,
)

API_URL = "https://api.modrinth.com/v2"
SITE_URL = "https://modrinth.com"


class _Hit(BaseModel):
    project_id: str
    slug: str
    title: str
    description: str = ""
    project_type: str = "modpack"
    icon_url: str | None = None
    downloads: int = 0


class _SearchResponse(BaseModel):
    hits: list[_Hit]
    total_hits: int = 0
    offset: int = 0


class _Project(BaseModel):
    id: str
    slug: str
    title: str
    description: str = ""
    project_type: str = "modpack"
    icon_url: str | None = None
    downloads: int = 0


class _File(BaseModel):
    filename: str
    url: str
    hashes: dict[str, str] = Field(default_factory=dict[str, str])
    size: int | None = None
    primary: bool = False


class _Version(BaseModel):
    id: str
    project_id: str
    name: str
    version_type: Literal["release", "beta", "alpha"] = "release"
    date_published: str = ""
    game_versions: list[str] = Field(default_factory=list[str])
    loaders: list[str] = Field(default_factory=list[str])
    files: list[_File] = Field(default_factory=list[_File])


def _project_url(project_type: str, slug: str) -> str:
    return f"{SITE_URL}/{project_type}/{slug}"


class Modrinth(Platform):
    """Modrinth. No API key is needed; identify your tool with `user_agent`."""

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
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, **params: Any) -> Any:
        return self.session.get_json(self.base_url + path, params=params)

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
        facets = [[f"project_type:{project_type}"]]
        if game_version:
            facets.append([f"versions:{game_version}"])
        if loader:
            facets.append([f"categories:{loader}"])
        data = _SearchResponse.model_validate(
            self._get(
                "/search",
                query=query,
                facets=json.dumps(facets),
                offset=offset,
                limit=limit,
            )
        )
        projects = tuple(
            Project(
                platform=self.name,
                id=hit.project_id,
                slug=hit.slug,
                name=hit.title,
                summary=hit.description,
                project_type=hit.project_type,
                icon_url=hit.icon_url,
                url=_project_url(hit.project_type, hit.slug),
                downloads=hit.downloads,
            )
            for hit in data.hits
        )
        return SearchResults(projects, data.total_hits, data.offset)

    def get_project(
        self, ref: str | int, *, project_type: ProjectType = "modpack"
    ) -> Project:
        data = _Project.model_validate(self._get(f"/project/{project_ref(ref)}"))
        return Project(
            platform=self.name,
            id=data.id,
            slug=data.slug,
            name=data.title,
            summary=data.description,
            project_type=data.project_type,
            icon_url=data.icon_url,
            url=_project_url(data.project_type, data.slug),
            downloads=data.downloads,
        )

    def list_releases(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> list[Release]:
        params: dict[str, str] = {}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader:
            params["loaders"] = json.dumps([loader])
        items = self._get(f"/project/{project.id}/version", **params)
        versions = [_Version.model_validate(item) for item in items]
        releases = [
            Release(
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
            )
            for version in versions
            if version.version_type == "release" or not release_only
        ]
        return sorted(releases, key=lambda item: item.published, reverse=True)
