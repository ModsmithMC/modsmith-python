import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .._support import write_json
from ..errors import UnsupportedError
from ._maven import maven_path


def default_game_path() -> Path:
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
    """A parsed version JSON, vanilla or from a mod loader."""

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
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


class GameDir:
    """A `.minecraft` directory and the layout of the files inside it."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @classmethod
    def default(cls) -> "GameDir":
        return cls(default_game_path())

    def __repr__(self) -> str:
        return f"GameDir({str(self.path)!r})"

    @property
    def versions_dir(self) -> Path:
        return self.path / "versions"

    @property
    def libraries_dir(self) -> Path:
        return self.path / "libraries"

    def version_json(self, version_id: str) -> Path:
        return self.versions_dir / version_id / f"{version_id}.json"

    def client_jar(self, version_id: str) -> Path:
        return self.versions_dir / version_id / f"{version_id}.jar"

    def library(self, coord: str) -> Path:
        return self.libraries_dir / maven_path(coord)

    def has_version(self, version_id: str) -> bool:
        return self.version_json(version_id).is_file()

    def installed_versions(self) -> list[str]:
        if not self.versions_dir.is_dir():
            return []
        names = sorted(path.name for path in self.versions_dir.iterdir())
        return [name for name in names if self.has_version(name)]

    def version(self, version_id: str) -> Version:
        if not self.has_version(version_id):
            raise UnsupportedError(f"Version {version_id} is not installed")
        return Version.load(self.version_json(version_id))

    def write_version(self, version_id: str, data: dict[str, Any]) -> None:
        write_json(self.version_json(version_id), data)
