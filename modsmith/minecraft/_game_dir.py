"""The layout of a game directory and its version files."""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .._fs import write_json
from ..errors import UnsupportedError
from ._maven import maven_path


def default_game_path() -> Path:
    """Return the official launcher's default game directory for this system.

    On Linux, the Flatpak directory is used if only that one exists.
    """
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA")
        return Path(appdata, ".minecraft") if appdata else home / ".minecraft"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "minecraft"
    default = home / ".minecraft"
    flatpak = home / ".var" / "app" / "com.mojang.Minecraft" / ".minecraft"
    return flatpak if not default.exists() and flatpak.exists() else default


@dataclass(frozen=True)
class Version:
    """A parsed version JSON, vanilla or from a mod loader.

    Attributes:
        id: The version id.
        inherits_from: The parent version of a loader version, or None.
        java_component: The Mojang runtime it asks for, or None.
        java_major: The major Java version it asks for, or None.
        client_url: Where to download the client jar, or None.
        client_sha1: The client jar's SHA-1, or None.
        client_size: The client jar's size in bytes, or None.
        raw: The original JSON data.
    """

    id: str
    inherits_from: str | None = None
    java_component: str | None = None
    java_major: int | None = None
    client_url: str | None = None
    client_sha1: str | None = None
    client_size: int | None = None
    raw: dict[str, Any] = field(
        default_factory=dict[str, Any], repr=False, compare=False
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Version":
        """Build a version from decoded JSON.

        Args:
            data: The version JSON.

        Returns:
            The parsed version.

        Raises:
            KeyError: The data has no ``id``.
        """
        java: dict[str, Any] = data.get("javaVersion") or {}
        downloads: dict[str, Any] = data.get("downloads") or {}
        client: dict[str, Any] = downloads.get("client") or {}
        return cls(
            id=data["id"],
            inherits_from=data.get("inheritsFrom"),
            java_component=java.get("component"),
            java_major=java.get("majorVersion"),
            client_url=client.get("url"),
            client_sha1=client.get("sha1"),
            client_size=client.get("size"),
            raw=data,
        )

    @classmethod
    def load(cls, path: Path) -> "Version":
        """Read a version from a JSON file."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


class GameDir:
    """A ``.minecraft`` directory and the layout of the files inside it.

    Args:
        path: The directory. It does not have to exist. A relative path is made
            absolute, so it stays valid if the working directory changes.

    Attributes:
        path: The absolute path of the directory.
    """

    def __init__(self, path: Path | str) -> None:
        self.path: Path = Path(path).resolve()

    @classmethod
    def default(cls) -> "GameDir":
        """Return the official launcher's default directory for this system."""
        return cls(default_game_path())

    def __repr__(self) -> str:
        return f"GameDir({str(self.path)!r})"

    @property
    def versions_dir(self) -> Path:
        """The directory that holds installed versions."""
        return self.path / "versions"

    @property
    def libraries_dir(self) -> Path:
        """The directory that holds libraries."""
        return self.path / "libraries"

    def version_json(self, version_id: str) -> Path:
        """Return the path of a version's JSON file."""
        return self.versions_dir / version_id / f"{version_id}.json"

    def client_jar(self, version_id: str) -> Path:
        """Return the path of a version's client jar."""
        return self.versions_dir / version_id / f"{version_id}.jar"

    def library(self, coord: str) -> Path:
        """Return the path of the library with a Maven coordinate."""
        return self.libraries_dir / maven_path(coord)

    def has_version(self, version_id: str) -> bool:
        """Return whether a version's JSON file exists."""
        return self.version_json(version_id).is_file()

    def installed_versions(self) -> list[str]:
        """List the installed version ids, sorted by name."""
        if not self.versions_dir.is_dir():
            return []
        names = sorted(path.name for path in self.versions_dir.iterdir())
        return [name for name in names if self.has_version(name)]

    def version(self, version_id: str) -> Version:
        """Read an installed version.

        Args:
            version_id: The version id.

        Returns:
            The parsed version.

        Raises:
            UnsupportedError: The version is not installed.
        """
        if not self.has_version(version_id):
            raise UnsupportedError(f"Version {version_id} is not installed")
        return Version.load(self.version_json(version_id))

    def write_version(self, version_id: str, data: dict[str, Any]) -> None:
        """Write a version's JSON file.

        Args:
            version_id: The version id.
            data: The version JSON.
        """
        write_json(self.version_json(version_id), data)
