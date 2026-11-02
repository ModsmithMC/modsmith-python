import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..core.download import Downloader
from ..core.errors import UnsupportedError
from ..core.http import HttpClient
from ..core.steps import Step
from ..minecraft.java import JavaResolver
from ..minecraft.versions import VersionService

SUPPORTED_KINDS = ("forge", "neoforge", "fabric")


@dataclass(frozen=True)
class LoaderSpec:
    kind: str
    version: str
    mc_version: str

    @classmethod
    def parse(cls, loader_id: str, mc_version: str) -> "LoaderSpec":
        kind, _, version = loader_id.lower().partition("-")
        if kind not in SUPPORTED_KINDS or not version:
            raise UnsupportedError(f"Unsupported mod loader: {loader_id}")
        return cls(kind, version.removeprefix(f"{mc_version}-"), mc_version)


@dataclass
class InstallContext:
    root: Path
    cache_dir: Path
    http: HttpClient
    downloader: Downloader
    versions: VersionService
    java: JavaResolver

    @property
    def libraries_dir(self) -> Path:
        return self.root / "libraries"

    def version_file(self, version_id: str) -> Path:
        return self.root / "versions" / version_id / f"{version_id}.json"

    def write_version(self, version_id: str, data: dict[str, Any]) -> None:
        path = self.version_file(version_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)


@dataclass
class LoaderPlan:
    version_id: str
    steps: list[Step] = field(default_factory=list)


class LoaderInstaller(Protocol):
    def prepare(self, spec: LoaderSpec, ctx: InstallContext) -> LoaderPlan: ...
