import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path, user_config_path, user_downloads_path

from .errors import ConfigError
from .paths import default_minecraft_dir

APP_NAME = "CurseCraft"
API_KEY_ENV = "CURSECRAFT_API_KEY"


def config_file() -> Path:
    return user_config_path(APP_NAME, appauthor=False) / "config.toml"


@dataclass
class Settings:
    minecraft_dir: Path = field(default_factory=default_minecraft_dir)
    instances_dir: Path | None = None
    cache_dir: Path = field(
        default_factory=lambda: user_cache_path(APP_NAME, appauthor=False)
    )
    manual_download_dir: Path = field(default_factory=user_downloads_path)
    curseforge_api_key: str | None = None
    curseforge_base_url: str = "https://api.curseforge.com"
    forge_maven_url: str = "https://maven.minecraftforge.net"
    neoforge_maven_url: str = "https://maven.neoforged.net/releases"
    fabric_meta_url: str = "https://meta.fabricmc.net"
    max_workers: int = 8
    chunk_size: int = 65536

    def __post_init__(self) -> None:
        if self.instances_dir is None:
            self.instances_dir = self.minecraft_dir / "cursecraft" / "instances"

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_file()
        values: dict[str, Any] = {}
        if path.is_file():
            try:
                values = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"Invalid config file {path}: {e}") from e

        known = cls.__dataclass_fields__
        unknown = set(values) - set(known)
        if unknown:
            raise ConfigError(f"Unknown settings in {path}: {sorted(unknown)}")
        for key in ("minecraft_dir", "instances_dir", "cache_dir", "manual_download_dir"):
            if key in values:
                values[key] = Path(values[key]).expanduser()

        api_key = os.getenv(API_KEY_ENV)
        if api_key:
            values["curseforge_api_key"] = api_key
        return cls(**values)
