"""Read and change the official launcher's profiles."""

import base64
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._support import slugify, write_json
from .errors import LauncherError
from .minecraft import GameDir

__all__ = ["Launcher", "Profile", "icon_data_uri", "is_running"]

PROFILE_FILES = ("launcher_profiles.json", "launcher_profiles_microsoft_store.json")
BACKUP_SUFFIX = ".modsmith.bak"
KEY_PREFIX = "modsmith-"
LAUNCHER_PROCESSES = frozenset(
    {
        "minecraft.exe",
        "minecraftlauncher.exe",
        "minecraft launcher",
        "minecraft-launcher",
    }
)


def parse_tasklist(output: str) -> set[str]:
    return {
        line.split('","')[0].strip('"').lower() for line in output.splitlines() if line
    }


def parse_ps(output: str) -> set[str]:
    return {
        line.rsplit("/", 1)[-1].strip().lower() for line in output.splitlines() if line
    }


def _process_names() -> set[str]:
    windows = sys.platform == "win32"
    command = (
        ["tasklist", "/FO", "CSV", "/NH"] if windows else ["ps", "-A", "-o", "comm="]
    )
    try:
        output = subprocess.run(
            command, capture_output=True, text=True, errors="replace", timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return parse_tasklist(output) if windows else parse_ps(output)


def is_running() -> bool:
    """Best-effort check for a running official launcher."""
    return bool(_process_names() & LAUNCHER_PROCESSES)


def icon_data_uri(data: bytes, content_type: str = "image/png") -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    version_id: str | None = None
    game_dir: str | None = None
    java_args: str | None = None
    icon: str | None = None

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> "Profile":
        return cls(
            key=key,
            name=data.get("name", key),
            version_id=data.get("lastVersionId"),
            game_dir=data.get("gameDir"),
            java_args=data.get("javaArgs"),
            icon=data.get("icon"),
        )


class Launcher:
    """The profiles of the official launcher that owns a `GameDir`."""

    def __init__(self, game: GameDir | None = None) -> None:
        self.game = game or GameDir.default()

    def profile_files(self) -> list[Path]:
        paths = [self.game.path / name for name in PROFILE_FILES]
        existing = [path for path in paths if path.is_file()]
        if not existing:
            raise LauncherError(
                f"No launcher profile in {self.game.path}; run the launcher once first"
            )
        return existing

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            raise LauncherError(f"Cannot parse {path.name}: {e}") from e

    def _update(self, change: Callable[[dict[str, Any]], None]) -> None:
        for path in self.profile_files():
            data = self._read(path)
            change(data.setdefault("profiles", {}))
            shutil.copy2(path, path.with_name(path.name + BACKUP_SUFFIX))
            write_json(path, data)

    def profiles(self) -> dict[str, Profile]:
        result: dict[str, Profile] = {}
        for path in self.profile_files():
            for key, value in self._read(path).get("profiles", {}).items():
                result.setdefault(key, Profile.from_dict(key, value))
        return result

    def add_profile(
        self,
        name: str,
        version_id: str,
        game_dir: Path | str,
        *,
        key: str | None = None,
        memory_mb: int | None = None,
        java_args: str | None = None,
        icon: str | None = None,
    ) -> str:
        """Create or update a profile and return its key."""
        key = key or KEY_PREFIX + slugify(name)
        now = _timestamp()
        values: dict[str, Any] = {
            "name": name,
            "type": "custom",
            "gameDir": str(game_dir),
            "lastVersionId": version_id,
            "lastUsed": now,
        }
        if memory_mb is not None:
            values["javaArgs"] = f"-Xmx{memory_mb}M"
        if java_args is not None:
            values["javaArgs"] = java_args
        if icon is not None:
            values["icon"] = icon

        def change(profiles: dict[str, Any]) -> None:
            existing = profiles.get(key)
            created = {"created": now} if existing is None else {}
            profiles[key] = {**(existing or {}), **created, **values}

        self._update(change)
        return key

    def remove_profile(self, key: str) -> None:
        self._update(lambda profiles: profiles.pop(key, None))
