import json
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, ValidationError

from ..errors import PackError, UnsupportedError
from ._model import FileRef, Modpack, PackEntry, Support, safe_relative


class PackFormat(ABC):
    """Reads one archive format. Subclass it and `register` it to add another."""

    name: ClassVar[str]
    index_file: ClassVar[str]

    @abstractmethod
    def parse(self, index: dict[str, Any], path: Path) -> Modpack:
        """Build a `Modpack` from the archive's decoded index file."""


_formats: list[PackFormat] = []


def register(format_: PackFormat) -> PackFormat:
    _formats.insert(0, format_)
    return format_


def load(path: Path | str) -> Modpack:
    """Read a modpack archive. Needs no network and no API key."""
    archive_path = Path(path)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            for format_ in _formats:
                if format_.index_file in names:
                    index = json.loads(archive.read(format_.index_file))
                    return format_.parse(index, archive_path)
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        raise PackError(f"{archive_path.name} is not a valid modpack: {e}") from e
    raise PackError(f"{archive_path.name} is not a known modpack format")


class _MrpackEnv(BaseModel):
    client: Support = "required"
    server: Support = "required"


class _MrpackFile(BaseModel):
    path: str
    hashes: dict[str, str]
    downloads: list[str]
    file_size: int | None = Field(default=None, alias="fileSize")
    env: _MrpackEnv = Field(default_factory=_MrpackEnv)


class _MrpackIndex(BaseModel):
    format_version: int = Field(alias="formatVersion")
    game: str
    name: str
    version_id: str = Field(alias="versionId")
    files: list[_MrpackFile]
    dependencies: dict[str, str]


class Mrpack(PackFormat):
    name = "mrpack"
    index_file = "modrinth.index.json"
    roots = {
        "common": "overrides",
        "client": "client-overrides",
        "server": "server-overrides",
    }

    def parse(self, index: dict[str, Any], path: Path) -> Modpack:
        try:
            data = _MrpackIndex.model_validate(index)
        except ValidationError as e:
            raise PackError(f"Invalid {self.index_file}: {e}") from e
        if data.game != "minecraft":
            raise UnsupportedError(f"Unsupported game: {data.game}")
        dependencies = dict(data.dependencies)
        minecraft = dependencies.pop("minecraft", None)
        if minecraft is None:
            raise PackError("Modpack does not declare a Minecraft version")
        if not dependencies:
            raise PackError("Modpack does not declare a mod loader")
        loader_kind, loader_version = next(iter(dependencies.items()))
        return Modpack(
            format=self.name,
            name=data.name,
            version=data.version_id,
            minecraft=minecraft,
            loader_kind=loader_kind,
            loader_version=loader_version,
            entries=tuple(
                PackEntry(
                    path=safe_relative(file.path),
                    urls=tuple(file.downloads),
                    hashes=file.hashes,
                    size=file.file_size,
                    client=file.env.client,
                    server=file.env.server,
                )
                for file in data.files
            ),
            archive=path,
            override_roots=self.roots,
        )


class _CfFile(BaseModel):
    project_id: int = Field(alias="projectID")
    file_id: int = Field(alias="fileID")
    required: bool = True


class _CfLoader(BaseModel):
    id: str
    primary: bool = False


class _CfMinecraft(BaseModel):
    version: str
    mod_loaders: list[_CfLoader] = Field(alias="modLoaders")
    recommended_ram: int | None = Field(default=None, alias="recommendedRam")


class _CfManifest(BaseModel):
    manifest_type: Literal["minecraftModpack"] = Field(alias="manifestType")
    name: str = "Modpack"
    version: str = ""
    overrides: str = "overrides"
    minecraft: _CfMinecraft
    files: list[_CfFile] = Field(default_factory=list[_CfFile])


class CurseForgePack(PackFormat):
    name = "curseforge"
    index_file = "manifest.json"

    def parse(self, index: dict[str, Any], path: Path) -> Modpack:
        try:
            data = _CfManifest.model_validate(index)
        except ValidationError as e:
            raise PackError(f"Invalid {self.index_file}: {e}") from e
        loaders = data.minecraft.mod_loaders
        if not loaders:
            raise PackError("Modpack does not declare a mod loader")
        loader = next((item for item in loaders if item.primary), loaders[0])
        kind, _, version = loader.id.partition("-")
        if not version:
            raise PackError(f"Invalid mod loader id: {loader.id}")

        def entry(file: _CfFile) -> PackEntry:
            support: Support = "required" if file.required else "optional"
            ref = FileRef(self.name, str(file.project_id), str(file.file_id))
            return PackEntry(client=support, server=support, ref=ref)

        return Modpack(
            format=self.name,
            name=data.name,
            version=data.version,
            minecraft=data.minecraft.version,
            loader_kind=kind,
            loader_version=version,
            entries=tuple(entry(file) for file in data.files),
            archive=path,
            override_roots={"common": data.overrides},
            memory_mb=data.minecraft.recommended_ram,
        )


register(CurseForgePack())
register(Mrpack())
