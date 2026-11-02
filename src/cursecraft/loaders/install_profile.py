import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import LoaderInstallError, UnsupportedError
from ..core.paths import maven_path


@dataclass(frozen=True)
class Library:
    name: str
    path: str
    url: str | None = None
    sha1: str | None = None
    size: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Library":
        artifact = (data.get("downloads") or {}).get("artifact") or {}
        return cls(
            name=data["name"],
            path=artifact.get("path") or maven_path(data["name"]),
            url=artifact.get("url") or None,
            sha1=artifact.get("sha1") or None,
            size=artifact.get("size") or None,
        )


@dataclass(frozen=True)
class Processor:
    jar: str
    classpath: list[str]
    args: list[str]
    outputs: dict[str, str]
    sides: list[str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Processor":
        return cls(
            jar=data["jar"],
            classpath=data.get("classpath") or [],
            args=data.get("args") or [],
            outputs=data.get("outputs") or {},
            sides=data.get("sides"),
        )

    def applies_to(self, side: str) -> bool:
        return self.sides is None or side in self.sides


@dataclass(frozen=True)
class InstallProfile:
    spec: int
    version: str
    minecraft: str
    json_path: str
    libraries: list[Library]
    processors: list[Processor]
    data: dict[str, str]

    @classmethod
    def from_dict(cls, data: dict[str, Any], side: str = "client") -> "InstallProfile":
        if "spec" not in data:
            raise UnsupportedError("Forge installers before Minecraft 1.13 are not supported")
        return cls(
            spec=data["spec"],
            version=data["version"],
            minecraft=data["minecraft"],
            json_path=data["json"],
            libraries=[Library.from_dict(lib) for lib in data.get("libraries", [])],
            processors=[Processor.from_dict(p) for p in data.get("processors", [])],
            data={key: value[side] for key, value in data.get("data", {}).items()},
        )

    def client_processors(self) -> list[Processor]:
        return [p for p in self.processors if p.applies_to("client")]


class InstallerJar:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            with zipfile.ZipFile(path) as archive:
                self.profile = InstallProfile.from_dict(
                    json.loads(archive.read("install_profile.json"))
                )
                self.version_json = json.loads(
                    archive.read(self.profile.json_path.lstrip("/"))
                )
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            raise LoaderInstallError(f"Malformed installer {path.name}: {e}") from e

    def extract_bundled_libraries(self, libraries_dir: Path) -> None:
        with zipfile.ZipFile(self.path) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.startswith("maven/"):
                    continue
                dest = libraries_dir / info.filename.removeprefix("maven/")
                if dest.is_file() and dest.stat().st_size == info.file_size:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(info))

    def extract_data_file(self, name: str, dest_dir: Path) -> Path:
        relative = name.lstrip("/")
        dest = dest_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(self.path) as archive:
                dest.write_bytes(archive.read(relative))
        except KeyError as e:
            raise LoaderInstallError(f"Installer is missing {name}") from e
        return dest


def replace_tokens(tokens: dict[str, str], value: str) -> str:
    result: list[str] = []
    index = 0
    closers = {"{": "}", "'": "'"}
    while index < len(value):
        char = value[index]
        index += 1
        if char == "\\":
            if index == len(value):
                raise LoaderInstallError(f"Bad escape in pattern: {value}")
            result.append(value[index])
            index += 1
        elif char in closers:
            buffer: list[str] = []
            while True:
                if index == len(value):
                    raise LoaderInstallError(f"Unclosed {char} in pattern: {value}")
                inner = value[index]
                index += 1
                if inner == "\\":
                    if index == len(value):
                        raise LoaderInstallError(f"Bad escape in pattern: {value}")
                    buffer.append(value[index])
                    index += 1
                elif inner == closers[char]:
                    break
                else:
                    buffer.append(inner)
            key = "".join(buffer)
            if char == "'":
                result.append(key)
            elif key in tokens:
                result.append(tokens[key])
            else:
                raise LoaderInstallError(f"Unknown variable {key} in pattern: {value}")
        else:
            result.append(char)
    return "".join(result)


class Variables:
    def __init__(self, libraries_dir: Path, tokens: dict[str, str]) -> None:
        self.libraries_dir = libraries_dir
        self.tokens = tokens

    @classmethod
    def build(
        cls,
        installer: InstallerJar,
        libraries_dir: Path,
        root: Path,
        minecraft_jar: Path,
        temp_dir: Path,
    ) -> "Variables":
        variables = cls(libraries_dir, {})
        for key, value in installer.profile.data.items():
            if value.startswith("[") and value.endswith("]"):
                resolved = str(variables.artifact(value))
            elif value.startswith("'") and value.endswith("'"):
                resolved = value[1:-1]
            else:
                resolved = str(installer.extract_data_file(value, temp_dir))
            variables.tokens[key] = resolved
        variables.tokens.update(
            SIDE="client",
            MINECRAFT_JAR=str(minecraft_jar),
            MINECRAFT_VERSION=installer.profile.minecraft,
            ROOT=str(root),
            INSTALLER=str(installer.path),
            LIBRARY_DIR=str(libraries_dir),
        )
        return variables

    def artifact(self, bracketed: str) -> Path:
        return self.libraries_dir / maven_path(bracketed[1:-1])

    def resolve(self, value: str) -> str:
        if value.startswith("[") and value.endswith("]"):
            return str(self.artifact(value))
        return replace_tokens(self.tokens, value)
