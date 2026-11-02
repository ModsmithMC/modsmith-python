import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core.errors import InstanceError

STATE_DIR = ".cursecraft"
RECORD_FILE = "instance.json"


@dataclass
class InstanceRecord:
    slug: str
    name: str
    source: str
    project_id: int | None
    file_id: int | None
    pack_version: str
    mc_version: str
    loader_id: str
    version_id: str
    profile_key: str
    files: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, str] = field(default_factory=dict)
    kept_overrides: list[str] = field(default_factory=list)
    installed_at: str = ""
    updated_at: str = ""


class InstanceStore:
    def __init__(self, instances_dir: Path) -> None:
        self.instances_dir = instances_dir

    def game_dir(self, slug: str) -> Path:
        return self.instances_dir / slug

    def _record_path(self, slug: str) -> Path:
        return self.game_dir(slug) / STATE_DIR / RECORD_FILE

    def exists(self, slug: str) -> bool:
        return self._record_path(slug).is_file()

    def load(self, slug: str) -> InstanceRecord:
        path = self._record_path(slug)
        if not path.is_file():
            raise InstanceError(f"No installed instance named {slug}")
        try:
            return InstanceRecord(**json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError) as e:
            raise InstanceError(f"Corrupt instance record for {slug}: {e}") from e

    def save(self, record: InstanceRecord) -> None:
        path = self._record_path(record.slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(
            json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temp.replace(path)

    def list(self) -> list[InstanceRecord]:
        if not self.instances_dir.is_dir():
            return []
        slugs = sorted(path.name for path in self.instances_dir.iterdir())
        return [self.load(slug) for slug in slugs if self.exists(slug)]

    def delete(self, slug: str) -> None:
        if not self.exists(slug):
            raise InstanceError(f"No installed instance named {slug}")
        shutil.rmtree(self.game_dir(slug))
