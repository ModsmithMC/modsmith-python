import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


def default_minecraft_dir() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.getenv("APPDATA")
        return Path(appdata, ".minecraft") if appdata else home / ".minecraft"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "minecraft"
    default = home / ".minecraft"
    flatpak = home / ".var" / "app" / "com.mojang.Minecraft" / ".minecraft"
    if not default.exists() and flatpak.exists():
        return flatpak
    return default


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .")
    return cleaned or "instance"


@dataclass(frozen=True)
class MavenCoord:
    group: str
    artifact: str
    version: str
    classifier: str | None = None
    extension: str = "jar"

    @classmethod
    def parse(cls, coord: str) -> "MavenCoord":
        body, _, extension = coord.partition("@")
        parts = body.split(":")
        if len(parts) < 3 or len(parts) > 4 or "@" in extension:
            raise ValueError(f"Invalid maven coord: {coord}")
        return cls(
            group=parts[0],
            artifact=parts[1],
            version=parts[2],
            classifier=parts[3] if len(parts) == 4 else None,
            extension=extension or "jar",
        )

    @property
    def path(self) -> str:
        name = f"{self.artifact}-{self.version}"
        if self.classifier:
            name += f"-{self.classifier}"
        group = self.group.replace(".", "/")
        return f"{group}/{self.artifact}/{self.version}/{name}.{self.extension}"


def maven_path(coord: str) -> str:
    return MavenCoord.parse(coord).path
