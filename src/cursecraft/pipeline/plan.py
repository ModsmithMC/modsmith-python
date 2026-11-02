from dataclasses import dataclass, field
from pathlib import Path

from ..instances.store import InstanceRecord
from ..loaders import LoaderSpec
from ..sources.base import PackFile, PackManifest, Project, ResolvedFile


@dataclass
class InstallPlan:
    source_name: str
    slug: str
    game_dir: Path
    archive: Path
    manifest: PackManifest
    loader: LoaderSpec
    files: list[ResolvedFile]
    project: Project | None = None
    pack_file: PackFile | None = None
    previous: InstanceRecord | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def manual_files(self) -> list[ResolvedFile]:
        return [file for file in self.files if file.url is None]

    @property
    def download_size(self) -> int:
        return sum(file.size or 0 for file in self.files if file.url)

    @property
    def is_update(self) -> bool:
        return self.previous is not None
