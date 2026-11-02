from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Project:
    source: str
    id: int
    slug: str
    name: str
    summary: str = ""
    icon_url: str | None = None
    website_url: str | None = None
    download_count: int = 0


@dataclass(frozen=True)
class SearchPage:
    projects: list[Project]
    total: int
    index: int


@dataclass(frozen=True)
class PackFile:
    id: int
    project_id: int
    name: str
    file_name: str
    url: str | None
    hash: str | None
    algo: str
    size: int | None


@dataclass(frozen=True)
class PackEntry:
    project_id: int
    file_id: int


@dataclass
class PackManifest:
    name: str
    version: str
    mc_version: str
    loader_id: str
    overrides: str = "overrides"
    recommended_ram: int | None = None
    entries: list[PackEntry] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedFile:
    project_id: int
    file_id: int
    file_name: str
    folder: str
    url: str | None
    hash: str | None
    algo: str
    size: int | None
    manual_url: str | None = None

    @property
    def relative_path(self) -> str:
        return f"{self.folder}/{self.file_name}"


class Source(Protocol):
    name: str

    def search(
        self, text: str, game_version: str | None = None, index: int = 0
    ) -> SearchPage: ...

    def get_project(self, ref: str | int) -> Project: ...

    def latest_pack_file(
        self, project: Project, allow_prerelease: bool = False
    ) -> PackFile: ...

    def read_manifest(self, data: dict[str, Any]) -> PackManifest: ...

    def resolve_files(self, manifest: PackManifest) -> list[ResolvedFile]: ...
