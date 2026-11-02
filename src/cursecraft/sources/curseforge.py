from dataclasses import dataclass
from typing import Any

from ..core.errors import ConfigError, SourceError
from ..core.http import HttpClient
from .base import PackEntry, PackFile, PackManifest, Project, ResolvedFile, SearchPage

GAME_ID = 432
CLASS_MODPACKS = 4471
RELEASE_TYPE_RELEASE = 1
HASH_ALGOS = {1: "sha1", 2: "md5"}
CLASS_FOLDERS = {
    6: "mods",
    12: "resourcepacks",
    17: "saves",
    4546: "config",
    6552: "shaderpacks",
    6945: "datapacks",
}
DEFAULT_FOLDER = "mods"
BATCH_SIZE = 500


@dataclass(frozen=True)
class CfFile:
    id: int
    mod_id: int
    display_name: str
    file_name: str
    release_type: int
    file_date: str
    download_url: str | None
    hash: str | None
    algo: str
    size: int | None
    is_server_pack: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CfFile":
        hashes = {
            HASH_ALGOS[h["algo"]]: h["value"]
            for h in data.get("hashes") or []
            if h.get("algo") in HASH_ALGOS
        }
        algo = "sha1" if "sha1" in hashes else "md5"
        return cls(
            id=data["id"],
            mod_id=data["modId"],
            display_name=data.get("displayName") or data["fileName"],
            file_name=data["fileName"],
            release_type=data.get("releaseType", RELEASE_TYPE_RELEASE),
            file_date=data.get("fileDate", ""),
            download_url=data.get("downloadUrl") or None,
            hash=hashes.get(algo),
            algo=algo,
            size=data.get("fileLength") or None,
            is_server_pack=bool(data.get("isServerPack")),
        )


@dataclass(frozen=True)
class CfMod:
    id: int
    name: str
    slug: str
    summary: str
    class_id: int | None
    icon_url: str | None
    website_url: str | None
    allow_distribution: bool | None
    download_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CfMod":
        logo = data.get("logo") or {}
        return cls(
            id=data["id"],
            name=data["name"],
            slug=data["slug"],
            summary=data.get("summary", ""),
            class_id=data.get("classId"),
            icon_url=logo.get("thumbnailUrl") or logo.get("url"),
            website_url=(data.get("links") or {}).get("websiteUrl") or None,
            allow_distribution=data.get("allowModDistribution"),
            download_count=data.get("downloadCount", 0),
        )

    def to_project(self) -> Project:
        return Project(
            source=CurseForgeSource.name,
            id=self.id,
            slug=self.slug,
            name=self.name,
            summary=self.summary,
            icon_url=self.icon_url,
            website_url=self.website_url,
            download_count=self.download_count,
        )


class CurseForgeClient:
    def __init__(self, http: HttpClient, api_key: str | None, base_url: str) -> None:
        self.http = http
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ConfigError(
                "A CurseForge API key is required: set CURSECRAFT_API_KEY "
                "or curseforge_api_key in the config file"
            )
        return {"Accept": "application/json", "x-api-key": self.api_key}

    def _get(self, path: str, **params: Any) -> Any:
        return self.http.get_json(
            self.base_url + path, headers=self.headers, params=params
        )

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.http.post_json(
            self.base_url + path, headers=self.headers, json=payload
        )

    def search(self, **params: Any) -> dict[str, Any]:
        return self._get("/v1/mods/search", gameId=GAME_ID, **params)

    def get_mod(self, mod_id: int) -> CfMod:
        return CfMod.from_dict(self._get(f"/v1/mods/{mod_id}")["data"])

    def get_mods(self, mod_ids: list[int]) -> list[CfMod]:
        mods: list[CfMod] = []
        for start in range(0, len(mod_ids), BATCH_SIZE):
            batch = mod_ids[start : start + BATCH_SIZE]
            data = self._post("/v1/mods", {"modIds": batch, "filterPcOnly": False})
            mods.extend(CfMod.from_dict(mod) for mod in data["data"])
        return mods

    def get_files(self, file_ids: list[int]) -> list[CfFile]:
        files: list[CfFile] = []
        for start in range(0, len(file_ids), BATCH_SIZE):
            batch = file_ids[start : start + BATCH_SIZE]
            data = self._post("/v1/mods/files", {"fileIds": batch})
            files.extend(CfFile.from_dict(file) for file in data["data"])
        return files

    def get_mod_files(self, mod_id: int, page_size: int = 50) -> list[CfFile]:
        data = self._get(f"/v1/mods/{mod_id}/files", pageSize=page_size)
        return [CfFile.from_dict(file) for file in data["data"]]


class CurseForgeSource:
    name = "curseforge"

    def __init__(self, client: CurseForgeClient) -> None:
        self.client = client

    def search(
        self, text: str, game_version: str | None = None, index: int = 0
    ) -> SearchPage:
        data = self.client.search(
            classId=CLASS_MODPACKS,
            searchFilter=text,
            gameVersion=game_version,
            index=index,
            pageSize=25,
        )
        projects = [CfMod.from_dict(mod).to_project() for mod in data["data"]]
        pagination = data.get("pagination") or {}
        return SearchPage(projects, pagination.get("totalCount", len(projects)), index)

    def get_project(self, ref: str | int) -> Project:
        text = str(ref).rstrip("/").rsplit("/", 1)[-1]
        if text.isdigit():
            return self.client.get_mod(int(text)).to_project()
        data = self.client.search(classId=CLASS_MODPACKS, slug=text, pageSize=1)
        if not data["data"]:
            raise SourceError(f"No CurseForge modpack found for {ref}")
        return CfMod.from_dict(data["data"][0]).to_project()

    def latest_pack_file(
        self, project: Project, allow_prerelease: bool = False
    ) -> PackFile:
        files = [f for f in self.client.get_mod_files(project.id) if not f.is_server_pack]
        if not files:
            raise SourceError(f"{project.name} has no client pack files")
        releases = [f for f in files if f.release_type == RELEASE_TYPE_RELEASE]
        candidates = files if allow_prerelease or not releases else releases
        file = max(candidates, key=lambda f: (f.file_date, f.id))
        return PackFile(
            id=file.id,
            project_id=project.id,
            name=file.display_name,
            file_name=file.file_name,
            url=file.download_url,
            hash=file.hash,
            algo=file.algo,
            size=file.size,
        )

    def read_manifest(self, data: dict[str, Any]) -> PackManifest:
        if data.get("manifestType") != "minecraftModpack":
            raise SourceError("Not a CurseForge modpack manifest")
        minecraft = data["minecraft"]
        loaders = minecraft.get("modLoaders") or []
        if not loaders:
            raise SourceError("Modpack does not declare a mod loader")
        loader = next((item for item in loaders if item.get("primary")), loaders[0])
        return PackManifest(
            name=data.get("name", "Modpack"),
            version=data.get("version", ""),
            mc_version=minecraft["version"],
            loader_id=loader["id"],
            overrides=data.get("overrides", "overrides"),
            recommended_ram=minecraft.get("recommendedRam"),
            entries=[
                PackEntry(entry["projectID"], entry["fileID"])
                for entry in data.get("files", [])
                if entry.get("required", True)
            ],
        )

    def resolve_files(self, manifest: PackManifest) -> list[ResolvedFile]:
        file_ids = [entry.file_id for entry in manifest.entries]
        files = {file.id: file for file in self.client.get_files(file_ids)}
        missing = [file_id for file_id in file_ids if file_id not in files]
        if missing:
            raise SourceError(f"CurseForge did not return files: {missing}")
        mods = {
            mod.id: mod
            for mod in self.client.get_mods(sorted({f.mod_id for f in files.values()}))
        }
        return [self._resolve(files[file_id], mods) for file_id in file_ids]

    def _resolve(self, file: CfFile, mods: dict[int, CfMod]) -> ResolvedFile:
        mod = mods.get(file.mod_id)
        allowed = mod is None or mod.allow_distribution is not False
        url = file.download_url if allowed else None
        website = mod.website_url if mod else None
        manual_url = None
        if url is None:
            base = website or f"https://www.curseforge.com/projects/{file.mod_id}"
            manual_url = f"{base.rstrip('/')}/files/{file.id}"
        return ResolvedFile(
            project_id=file.mod_id,
            file_id=file.id,
            file_name=file.file_name,
            folder=CLASS_FOLDERS.get(mod.class_id if mod else None, DEFAULT_FOLDER),
            url=url,
            hash=file.hash,
            algo=file.algo,
            size=file.size,
            manual_url=manual_url,
        )
