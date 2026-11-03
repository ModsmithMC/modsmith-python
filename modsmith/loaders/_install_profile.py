"""Read Forge and NeoForge installer jars and expand their variables."""

import json
import zipfile
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import LoaderError, UnsupportedError
from ..minecraft import maven_path


class _Artifact(BaseModel):
    """A library's ``downloads.artifact`` object."""

    path: str | None = None
    url: str | None = None
    sha1: str | None = None
    size: int | None = None


class _Downloads(BaseModel):
    """A library's ``downloads`` object."""

    artifact: _Artifact | None = None


class Library(BaseModel):
    """A library listed by an installer.

    Attributes:
        name: Its Maven coordinate.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str
    downloads: _Downloads | None = None

    @property
    def _artifact(self) -> _Artifact:
        """The download details, or an empty artifact if there are none."""
        if self.downloads and self.downloads.artifact:
            return self.downloads.artifact
        return _Artifact()

    @property
    def path(self) -> str:
        """Its path inside the libraries directory."""
        return self._artifact.path or maven_path(self.name)

    @property
    def url(self) -> str | None:
        """Where to download it, or None if it has no URL."""
        return self._artifact.url or None

    @property
    def hashes(self) -> dict[str, str]:
        """Its expected digests keyed by algorithm name."""
        sha1 = self._artifact.sha1
        return {"sha1": sha1} if sha1 else {}

    @property
    def size(self) -> int | None:
        """Its size in bytes, or None if unknown."""
        return self._artifact.size or None


class Processor(BaseModel):
    """One step of an install: a jar to run and the files it produces.

    Attributes:
        jar: The Maven coordinate of the jar to run.
        classpath: Maven coordinates of the jar's dependencies.
        args: Command-line arguments, which can contain variables.
        outputs: Expected SHA-1 digests keyed by output file.
        sides: The sides it runs on, or None for every side.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    jar: str
    classpath: list[str] = Field(default_factory=list[str])
    args: list[str] = Field(default_factory=list[str])
    outputs: dict[str, str] = Field(default_factory=dict[str, str])
    sides: list[str] | None = None

    def applies_to(self, side: str) -> bool:
        """Return whether this step runs on ``side``."""
        return self.sides is None or side in self.sides


class _DataValue(BaseModel):
    """A variable's value for each side."""

    client: str
    server: str = ""


class InstallProfile(BaseModel):
    """The ``install_profile.json`` inside a Forge or NeoForge installer.

    Attributes:
        spec: The profile format version.
        version: The version id it installs.
        minecraft: The Minecraft version it targets.
        json_path: The path of the version JSON inside the installer.
        libraries: The libraries the processors need.
        processors: The install steps, in order.
        data: The variables available to the processors.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, populate_by_name=True)

    spec: int
    version: str
    minecraft: str
    json_path: str = Field(alias="json")
    libraries: list[Library] = Field(default_factory=list[Library])
    processors: list[Processor] = Field(default_factory=list[Processor])
    data: dict[str, _DataValue] = Field(default_factory=dict[str, _DataValue])

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "InstallProfile":
        """Validate a decoded profile.

        Args:
            data: The decoded JSON.

        Returns:
            The profile.

        Raises:
            UnsupportedError: The profile is from before Minecraft 1.13.
        """
        if "spec" not in data:
            raise UnsupportedError("Installers before Minecraft 1.13 are not supported")
        return cls.model_validate(data)

    def client_processors(self) -> list[Processor]:
        """Return the steps that run on the client."""
        return [p for p in self.processors if p.applies_to("client")]


class InstallerJar:
    """A downloaded Forge or NeoForge installer, read as an archive.

    Args:
        path: The installer jar.

    Attributes:
        path: The installer jar.
        profile: Its install profile.
        version_json: Its version JSON.

    Raises:
        LoaderError: The installer is malformed.
        UnsupportedError: The installer is older than Minecraft 1.13.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            with zipfile.ZipFile(path) as archive:
                self.profile: InstallProfile = InstallProfile.parse(
                    json.loads(archive.read("install_profile.json"))
                )
                self.version_json: dict[str, Any] = json.loads(
                    archive.read(self.profile.json_path.lstrip("/"))
                )
        except (zipfile.BadZipFile, KeyError, ValueError, ValidationError) as e:
            raise LoaderError(f"Malformed installer {path.name}: {e}") from e

    @property
    def version_id(self) -> str:
        """The id declared by the version JSON."""
        return self.version_json["id"]

    @property
    def version_libraries(self) -> list[Library]:
        """The libraries the version JSON lists for the running game."""
        items = self.version_json.get("libraries", [])
        return [Library.model_validate(item) for item in items]

    def extract_bundled_libraries(self, libraries_dir: Path) -> None:
        """Copy the libraries bundled in the installer into ``libraries_dir``.

        Args:
            libraries_dir: The game's libraries directory.
        """
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
        """Extract a file named by the install profile.

        Args:
            name: The file's path inside the installer.
            dest_dir: The directory to extract into.

        Returns:
            The extracted file.

        Raises:
            LoaderError: The installer does not contain the file.
        """
        relative = name.lstrip("/")
        dest = dest_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(self.path) as archive:
                dest.write_bytes(archive.read(relative))
        except KeyError as e:
            raise LoaderError(f"Installer is missing {name}") from e
        return dest


# Characters that open a variable or a literal, and what closes each.
CLOSERS = {"{": "}", "'": "'"}


def _escaped(value: str, index: int) -> tuple[str, int]:
    """Return the character after a backslash, and the index after it."""
    if index == len(value):
        raise LoaderError(f"Bad escape in pattern: {value}")
    return value[index], index + 1


def _read_until(value: str, index: int, opener: str) -> tuple[str, int]:
    """Read up to the character that closes ``opener``, resolving escapes."""
    text: list[str] = []
    while True:
        if index == len(value):
            raise LoaderError(f"Unclosed {opener} in pattern: {value}")
        char = value[index]
        index += 1
        if char == "\\":
            char, index = _escaped(value, index)
        elif char == CLOSERS[opener]:
            return "".join(text), index
        text.append(char)


def replace_tokens(tokens: dict[str, str], value: str) -> str:
    """Expand ``{NAME}`` and ``'literal'`` as the installer format defines them.

    Args:
        tokens: The variables.
        value: The text to expand.

    Returns:
        The expanded text.

    Raises:
        LoaderError: The text is malformed or uses an unknown variable.
    """
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        index += 1
        if char == "\\":
            char, index = _escaped(value, index)
        elif char in CLOSERS:
            name, index = _read_until(value, index, char)
            if char == "{":
                if name not in tokens:
                    raise LoaderError(f"Unknown variable {name} in pattern: {value}")
                name = tokens[name]
            char = name
        result.append(char)
    return "".join(result)


class Variables:
    """The variables available to a processor.

    Args:
        libraries_dir: The game's libraries directory.
        tokens: The values keyed by variable name.

    Attributes:
        libraries_dir: The game's libraries directory.
        tokens: The values keyed by variable name.
    """

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
        """Build the variables for an install, extracting the files they refer to.

        Args:
            installer: The installer.
            libraries_dir: The game's libraries directory.
            root: The game directory.
            minecraft_jar: The vanilla client jar.
            temp_dir: Where to extract data files.

        Returns:
            The variables.

        Raises:
            LoaderError: The installer does not contain a file it refers to.
        """
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
        """Return the path of a ``[group:artifact:version]`` reference."""
        return self.libraries_dir / maven_path(bracketed[1:-1])

    def resolve(self, value: str) -> str:
        """Expand a processor value.

        Args:
            value: A ``[coordinate]`` reference, or text with variables.

        Returns:
            The expanded value.

        Raises:
            LoaderError: The text is malformed or uses an unknown variable.
        """
        if value.startswith("[") and value.endswith("]"):
            return str(self.artifact(value))
        return replace_tokens(self.tokens, value)
