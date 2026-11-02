import dataclasses
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ..errors import PlatformError
from ..net import Session
from ..packs import Modpack, PackEntry
from ._base import (
    Platform,
    Project,
    ProjectType,
    Release,
    ReleaseFile,
    ReleaseType,
    SearchResults,
    project_ref,
)

API_URL = "https://api.curseforge.com"
GAME_ID = 432
BATCH_SIZE = 500
PAGE_SIZE = 50
HASH_ALGORITHMS = {1: "sha1", 2: "md5"}
RELEASE_TYPES: dict[int, ReleaseType] = {1: "release", 2: "beta", 3: "alpha"}
PROJECT_CLASSES: dict[str, int] = {
    "mod": 6,
    "modpack": 4471,
    "resourcepack": 12,
    "shader": 6552,
}
CLASS_FOLDERS = {
    6: "mods",
    12: "resourcepacks",
    17: "saves",
    4546: "config",
    6552: "shaderpacks",
    6945: "datapacks",
}
LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}


class _Schema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class _Hash(_Schema):
    value: str
    algo: int


class _File(_Schema):
    id: int
    mod_id: int
    display_name: str = ""
    file_name: str
    release_type: Literal[1, 2, 3] = 1
    file_date: str = ""
    file_length: int | None = None
    download_url: str | None = None
    hashes: list[_Hash] = Field(default_factory=list[_Hash])
    is_server_pack: bool | None = False
    game_versions: list[str] = Field(default_factory=list[str])

    @property
    def hash_map(self) -> dict[str, str]:
        return {
            HASH_ALGORITHMS[item.algo]: item.value
            for item in self.hashes
            if item.algo in HASH_ALGORITHMS
        }

    def to_release(self, platform: str) -> Release:
        urls = (self.download_url,) if self.download_url else ()
        return Release(
            platform=platform,
            id=str(self.id),
            project_id=str(self.mod_id),
            name=self.display_name or self.file_name,
            release_type=RELEASE_TYPES[self.release_type],
            published=self.file_date,
            game_versions=tuple(self.game_versions),
            files=(ReleaseFile(self.file_name, urls, self.hash_map, self.file_length),),
        )


class _Logo(_Schema):
    url: str | None = None
    thumbnail_url: str | None = None


class _Links(_Schema):
    website_url: str | None = None


class _Mod(_Schema):
    id: int
    name: str
    slug: str
    summary: str = ""
    class_id: int | None = None
    logo: _Logo | None = None
    links: _Links | None = None
    allow_mod_distribution: bool | None = None
    download_count: int = 0

    def to_project(self, platform: str, project_type: str) -> Project:
        logo = self.logo
        return Project(
            platform=platform,
            id=str(self.id),
            slug=self.slug,
            name=self.name,
            summary=self.summary,
            project_type=project_type,
            icon_url=(logo.thumbnail_url or logo.url) if logo else None,
            url=self.links.website_url if self.links else None,
            downloads=self.download_count,
        )


class CurseForge(Platform):
    """CurseForge. Requires an API key from console.curseforge.com."""

    name: ClassVar[str] = "curseforge"

    def __init__(
        self,
        api_key: str,
        *,
        session: Session | None = None,
        base_url: str = API_URL,
    ) -> None:
        super().__init__(session)
        if not api_key:
            raise PlatformError("CurseForge requires an API key")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "x-api-key": self.api_key}

    def _get(self, path: str, **params: Any) -> Any:
        return self.session.get_json(
            self.base_url + path, headers=self._headers, params=params
        )

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.session.post_json(
            self.base_url + path, headers=self._headers, json=payload
        )

    def _search(self, project_type: str, **params: Any) -> Any:
        return self._get(
            "/v1/mods/search",
            gameId=GAME_ID,
            classId=PROJECT_CLASSES[project_type],
            **params,
        )

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
        data = self._search(
            project_type,
            searchFilter=query,
            gameVersion=game_version,
            modLoaderType=LOADER_TYPES.get(loader or ""),
            index=offset,
            pageSize=limit,
        )
        mods = [_Mod.model_validate(item) for item in data["data"]]
        projects = tuple(mod.to_project(self.name, project_type) for mod in mods)
        pagination: dict[str, Any] = data.get("pagination") or {}
        return SearchResults(projects, pagination.get("totalCount", len(mods)), offset)

    def get_project(
        self, ref: str | int, *, project_type: ProjectType = "modpack"
    ) -> Project:
        text = project_ref(ref)
        if text.isdigit():
            mod = _Mod.model_validate(self._get(f"/v1/mods/{text}")["data"])
            return mod.to_project(self.name, project_type)
        data = self._search(project_type, slug=text, pageSize=1)
        if not data["data"]:
            raise PlatformError(f"No CurseForge {project_type} found for {ref}")
        return _Mod.model_validate(data["data"][0]).to_project(self.name, project_type)

    def list_releases(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> list[Release]:
        data = self._get(
            f"/v1/mods/{project.id}/files",
            gameVersion=game_version,
            modLoaderType=LOADER_TYPES.get(loader or ""),
            pageSize=PAGE_SIZE,
        )
        files = [_File.model_validate(item) for item in data["data"]]
        releases = [
            file.to_release(self.name)
            for file in files
            if not file.is_server_pack and (file.release_type == 1 or not release_only)
        ]
        return sorted(releases, key=lambda item: item.published, reverse=True)

    def _files(self, file_ids: list[int]) -> dict[int, _File]:
        files: dict[int, _File] = {}
        for start in range(0, len(file_ids), BATCH_SIZE):
            batch = file_ids[start : start + BATCH_SIZE]
            data = self._post("/v1/mods/files", {"fileIds": batch})
            for item in data["data"]:
                file = _File.model_validate(item)
                files[file.id] = file
        return files

    def _mods(self, mod_ids: list[int]) -> dict[int, _Mod]:
        mods: dict[int, _Mod] = {}
        for start in range(0, len(mod_ids), BATCH_SIZE):
            batch = mod_ids[start : start + BATCH_SIZE]
            data = self._post("/v1/mods", {"modIds": batch, "filterPcOnly": False})
            for item in data["data"]:
                mod = _Mod.model_validate(item)
                mods[mod.id] = mod
        return mods

    def _resolved_entry(self, entry: PackEntry, file: _File, mod: _Mod | None) -> PackEntry:
        allowed = mod is None or mod.allow_mod_distribution is not False
        url = file.download_url if allowed else None
        manual_url = None
        if url is None:
            website = mod.links.website_url if mod and mod.links else None
            base = website or f"https://www.curseforge.com/projects/{file.mod_id}"
            manual_url = f"{base.rstrip('/')}/files/{file.id}"
        folder = CLASS_FOLDERS.get(mod.class_id or 6 if mod else 6, "mods")
        return dataclasses.replace(
            entry,
            path=f"{folder}/{file.file_name}",
            urls=(url,) if url else (),
            hashes=file.hash_map,
            size=file.file_length,
            manual_url=manual_url,
        )

    def resolve(self, pack: Modpack) -> Modpack:
        """Look up download details.

        A file whose author disallows third-party downloads stays unresolved
        and carries a `manual_url`; so does a file CurseForge no longer lists.
        """
        pending = [
            entry
            for entry in pack.entries
            if entry.ref and entry.ref.platform == self.name and not entry.is_resolved
        ]
        ids = [int(entry.ref.file_id) for entry in pending if entry.ref]
        files = self._files(ids)
        mods = self._mods(sorted({file.mod_id for file in files.values()}))

        def resolved(entry: PackEntry) -> PackEntry:
            if entry.ref is None or entry.ref.platform != self.name:
                return entry
            file = files.get(int(entry.ref.file_id))
            if file is None:
                return entry
            return self._resolved_entry(entry, file, mods.get(file.mod_id))

        return pack.with_entries(tuple(resolved(entry) for entry in pack.entries))
