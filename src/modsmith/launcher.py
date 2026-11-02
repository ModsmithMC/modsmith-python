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
    """Extract lowercase process names from ``tasklist /FO CSV`` output."""
    return {
        line.split('","')[0].strip('"').lower() for line in output.splitlines() if line
    }


def parse_ps(output: str) -> set[str]:
    """Extract lowercase process names from ``ps -o comm=`` output."""
    return {
        line.rsplit("/", 1)[-1].strip().lower() for line in output.splitlines() if line
    }


def _process_names() -> set[str]:
    """List running process names, or nothing if they cannot be read."""
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
    """Return whether the official launcher appears to be running.

    This is best-effort: it returns False if the process list cannot be read.
    """
    return bool(_process_names() & LAUNCHER_PROCESSES)


def icon_data_uri(data: bytes, content_type: str = "image/png") -> str:
    """Encode an image as the data URI that launcher profiles use for icons.

    Args:
        data: The image file's contents.
        content_type: The image's media type.

    Returns:
        The data URI, ready for the ``icon`` argument of `Launcher.add_profile`.
    """
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _timestamp() -> str:
    """Return the current UTC time in the launcher's format."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Profile:
    """One launcher profile.

    Attributes:
        key: The profile's key in the launcher's file.
        name: The display name.
        version_id: The version it starts, or None.
        game_dir: Its game directory, or None for the default.
        java_args: Its JVM arguments, or None.
        icon: Its icon, as a name or data URI, or None.
    """

    key: str
    name: str
    version_id: str | None = None
    game_dir: str | None = None
    java_args: str | None = None
    icon: str | None = None

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> "Profile":
        """Build a profile from the launcher's JSON.

        Args:
            key: The profile's key.
            data: The profile's JSON.

        Returns:
            The parsed profile.
        """
        return cls(
            key=key,
            name=data.get("name", key),
            version_id=data.get("lastVersionId"),
            game_dir=data.get("gameDir"),
            java_args=data.get("javaArgs"),
            icon=data.get("icon"),
        )


class Launcher:
    """The profiles of the official launcher that owns a `GameDir`.

    Changes go to every profile file that exists, and each file is backed up
    first. Keep the launcher closed while changing profiles.

    Args:
        game: The game directory. Defaults to `GameDir.default`.

    Attributes:
        game: The game directory.
    """

    def __init__(self, game: GameDir | None = None) -> None:
        self.game = game or GameDir.default()

    def profile_files(self) -> list[Path]:
        """List the launcher's profile files that exist.

        Returns:
            The paths.

        Raises:
            LauncherError: There are none, because the launcher has never run here.
        """
        paths = [self.game.path / name for name in PROFILE_FILES]
        existing = [path for path in paths if path.is_file()]
        if not existing:
            raise LauncherError(
                f"No launcher profile in {self.game.path}; run the launcher once first"
            )
        return existing

    def _read(self, path: Path) -> dict[str, Any]:
        """Parse a profile file, allowing a byte order mark."""
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            raise LauncherError(f"Cannot parse {path.name}: {e}") from e

    def _update(self, change: Callable[[dict[str, Any]], None]) -> None:
        """Apply a change to the profiles in every file, with a backup."""
        for path in self.profile_files():
            data = self._read(path)
            change(data.setdefault("profiles", {}))
            shutil.copy2(path, path.with_name(path.name + BACKUP_SUFFIX))
            write_json(path, data)

    def profiles(self) -> dict[str, Profile]:
        """Read every profile.

        Returns:
            The profiles by key. If files disagree, the first file wins.

        Raises:
            LauncherError: No profile file exists, or one cannot be parsed.
        """
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
        """Create or update a profile and return its key.

        Fields you do not set on an existing profile are kept.

        Args:
            name: The display name.
            version_id: The version to start.
            game_dir: The instance's directory. It is stored as an absolute path.
            key: The profile's key. Defaults to ``modsmith-`` and a slug of ``name``.
            memory_mb: The maximum heap size. Ignored if ``java_args`` is set.
            java_args: The JVM arguments.
            icon: The icon, such as a result of `icon_data_uri`.

        Returns:
            The profile's key.

        Raises:
            LauncherError: No profile file exists, or one cannot be parsed.
        """
        key = key or KEY_PREFIX + slugify(name)
        now = _timestamp()
        values: dict[str, Any] = {
            "name": name,
            "type": "custom",
            "gameDir": str(Path(game_dir).resolve()),
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
        """Remove a profile. A key that does not exist is ignored.

        Args:
            key: The profile's key.

        Raises:
            LauncherError: No profile file exists, or one cannot be parsed.
        """
        self._update(lambda profiles: profiles.pop(key, None))
