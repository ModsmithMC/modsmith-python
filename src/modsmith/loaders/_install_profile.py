import json
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import LoaderError, UnsupportedError
from ..minecraft import maven_path


class _Artifact(BaseModel):
    path: str | None = None
    url: str | None = None
    sha1: str | None = None
    size: int | None = None


class _Downloads(BaseModel):
    artifact: _Artifact | None = None


class Library(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    downloads: _Downloads | None = None

    @property
    def _artifact(self) -> _Artifact:
        if self.downloads and self.downloads.artifact:
            return self.downloads.artifact
        return _Artifact()

    @property
    def path(self) -> str:
        return self._artifact.path or maven_path(self.name)

    @property
    def url(self) -> str | None:
        return self._artifact.url or None

    @property
    def hashes(self) -> dict[str, str]:
        sha1 = self._artifact.sha1
        return {"sha1": sha1} if sha1 else {}

    @property
    def size(self) -> int | None:
        return self._artifact.size or None


class Processor(BaseModel):
    model_config = ConfigDict(frozen=True)

    jar: str
    classpath: list[str] = Field(default_factory=list[str])
    args: list[str] = Field(default_factory=list[str])
    outputs: dict[str, str] = Field(default_factory=dict[str, str])
    sides: list[str] | None = None

    def applies_to(self, side: str) -> bool:
        return self.sides is None or side in self.sides


class _DataValue(BaseModel):
    client: str
    server: str = ""


class InstallProfile(BaseModel):
    """The `install_profile.json` inside a Forge or NeoForge installer."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    spec: int
    version: str
    minecraft: str
    json_path: str = Field(alias="json")
    libraries: list[Library] = Field(default_factory=list[Library])
    processors: list[Processor] = Field(default_factory=list[Processor])
    data: dict[str, _DataValue] = Field(default_factory=dict[str, _DataValue])

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "InstallProfile":
        if "spec" not in data:
            raise UnsupportedError("Installers before Minecraft 1.13 are not supported")
        return cls.model_validate(data)

    def client_processors(self) -> list[Processor]:
        return [p for p in self.processors if p.applies_to("client")]


class InstallerJar:
    """A downloaded Forge or NeoForge installer, read as an archive."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            with zipfile.ZipFile(path) as archive:
                self.profile = InstallProfile.parse(
                    json.loads(archive.read("install_profile.json"))
                )
                self.version_json: dict[str, Any] = json.loads(
                    archive.read(self.profile.json_path.lstrip("/"))
                )
        except (zipfile.BadZipFile, KeyError, ValueError, ValidationError) as e:
            raise LoaderError(f"Malformed installer {path.name}: {e}") from e

    @property
    def version_id(self) -> str:
        return self.version_json["id"]

    @property
    def version_libraries(self) -> list[Library]:
        items = self.version_json.get("libraries", [])
        return [Library.model_validate(item) for item in items]

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
            raise LoaderError(f"Installer is missing {name}") from e
        return dest


def replace_tokens(tokens: dict[str, str], value: str) -> str:
    """Expand `{NAME}` and `'literal'` as the installer format defines them."""
    result: list[str] = []
    closers = {"{": "}", "'": "'"}
    index = 0

    def escaped() -> str:
        nonlocal index
        if index == len(value):
            raise LoaderError(f"Bad escape in pattern: {value}")
        char = value[index]
        index += 1
        return char

    while index < len(value):
        char = value[index]
        index += 1
        if char == "\\":
            result.append(escaped())
        elif char in closers:
            key: list[str] = []
            while True:
                if index == len(value):
                    raise LoaderError(f"Unclosed {char} in pattern: {value}")
                inner = value[index]
                index += 1
                if inner == "\\":
                    key.append(escaped())
                elif inner == closers[char]:
                    break
                else:
                    key.append(inner)
            name = "".join(key)
            if char == "'":
                result.append(name)
            elif name in tokens:
                result.append(tokens[name])
            else:
                raise LoaderError(f"Unknown variable {name} in pattern: {value}")
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
        for key, data in installer.profile.data.items():
            value = data.client
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
