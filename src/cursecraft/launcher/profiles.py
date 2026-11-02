import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.errors import LauncherError

PROFILE_FILES = ("launcher_profiles.json", "launcher_profiles_microsoft_store.json")
BACKUP_SUFFIX = ".cursecraft.bak"


class ProfileStore:
    def __init__(self, minecraft_dir: Path) -> None:
        self.minecraft_dir = minecraft_dir

    def paths(self) -> list[Path]:
        paths = [self.minecraft_dir / name for name in PROFILE_FILES]
        existing = [path for path in paths if path.is_file()]
        if not existing:
            raise LauncherError(
                f"No launcher profile found in {self.minecraft_dir}; "
                "run the official launcher once first"
            )
        return existing

    def _update(self, change: Callable[[dict[str, Any]], None]) -> None:
        for path in self.paths():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except ValueError as e:
                raise LauncherError(f"Cannot parse {path.name}: {e}") from e
            change(data.setdefault("profiles", {}))
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            shutil.copy2(path, path.with_name(path.name + BACKUP_SUFFIX))
            os.replace(temp, path)

    def get(self, key: str) -> dict[str, Any] | None:
        for path in self.paths():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            profile = data.get("profiles", {}).get(key)
            if profile is not None:
                return profile
        return None

    def upsert(self, key: str, values: dict[str, Any]) -> None:
        def change(profiles: dict[str, Any]) -> None:
            profiles[key] = {**profiles.get(key, {}), **values}

        self._update(change)

    def remove(self, key: str) -> None:
        self._update(lambda profiles: profiles.pop(key, None))
