"""Loaders installed from a metadata service: Fabric and Quilt."""

from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Self

from .._locks import GAME_LOCK, file_lock
from ..errors import NetworkError
from ..minecraft import GameDir, Version, install_version, maven_path
from ..net import Resource, Session, download
from ..net._session import session_scope
from ..progress import CancelToken, ProgressCallback
from ._base import (
    Loader,
    LoaderVersion,
    is_stable,
    library_versions,
    recommend,
    register,
)

HASH_FIELDS = ("sha512", "sha256", "sha1", "md5")
# The metadata services answer these for a Minecraft version they do not know.
UNKNOWN_VERSION = (400, 404)


@dataclass(frozen=True)
class MetaLoader(Loader):
    """A loader described by a version JSON from a metadata service.

    Attributes:
        meta_url: The service's base URL.
        default_maven: The repository for libraries that do not name one.
        library: The loader's own library, as ``group:artifact``.
    """

    meta_url: str = ""
    default_maven: ClassVar[str]
    library: ClassVar[str]

    @classmethod
    def from_version(cls, version: Version, minecraft: str) -> Self | None:
        """Recognise the loader by its own library on the class path."""
        found = library_versions(version).get(cls.library)
        return cls(found, minecraft) if found else None

    @abstractmethod
    def profile_url(self) -> str:
        """Return where this loader's version JSON is served."""

    @classmethod
    def available(
        cls,
        minecraft: str,
        *,
        session: Session | None = None,
        meta_url: str | None = None,
    ) -> list[LoaderVersion]:
        """List this loader's versions for a Minecraft version, newest first.

        Versions such as ``0.20.0-beta.9`` are pre-releases. Fabric marks only
        its current build as stable, so that one is recommended; otherwise the
        newest stable version is.

        Args:
            minecraft: The Minecraft version.
            session: The session to use. A temporary one is created if omitted.
            meta_url: The metadata service. Defaults to the loader's own.

        Returns:
            The versions, empty if the service does not know the Minecraft
            version.

        Raises:
            NetworkError: The service could not be reached.
        """
        base = (meta_url or cls.meta_url).rstrip("/")
        url = f"{base}/versions/loader/{minecraft}"
        with session_scope(session) as client:
            response = client.request("GET", url, accept=UNKNOWN_VERSION)
            if response.status_code in UNKNOWN_VERSION:
                return []
            try:
                items: list[dict[str, Any]] = response.json()
            except ValueError as e:
                raise NetworkError(f"Invalid JSON from {url}") from e
        found: list[LoaderVersion] = []
        marked: str | None = None
        for item in items:
            info: dict[str, Any] = item.get("loader") or {}
            version = info.get("version")
            if isinstance(version, str):
                found.append(
                    LoaderVersion(cls.kind, version, minecraft, is_stable(version))
                )
                if info.get("stable") and marked is None:
                    marked = version
        return recommend(found, marked)

    def expected_id(self) -> str:
        """Return the version id that the metadata service gives this loader."""
        return f"{self.kind}-loader-{self.version}-{self.minecraft}"

    def profile(self, session: Session | None = None) -> dict[str, Any]:
        """Fetch this loader's version JSON.

        Args:
            session: The session to use. A temporary one is created if omitted.

        Returns:
            The decoded JSON.

        Raises:
            NetworkError: The service failed or does not know this version.
        """
        with session_scope(session) as client:
            return client.get_json(self.profile_url())

    def version_id(
        self, *, session: Session | None = None, cache_dir: Path | None = None
    ) -> str:
        """Return the id from the metadata service.

        Args:
            session: The session to use. A temporary one is created if omitted.
            cache_dir: Not used by this loader.

        Returns:
            The version id.

        Raises:
            NetworkError: The service failed or does not know this version.
        """
        return self.profile(session)["id"]

    def _resource(self, library: dict[str, Any], game: GameDir) -> Resource:
        """Describe where to download one of the profile's libraries."""
        path = maven_path(library["name"])
        base: str = library.get("url") or self.default_maven
        hashes = {name: library[name] for name in HASH_FIELDS if library.get(name)}
        return Resource.of(
            f"{base.rstrip('/')}/{path}",
            game.libraries_dir / path,
            hashes,
            library.get("size"),
        )

    def install(
        self,
        game: GameDir,
        *,
        java: Path | None = None,
        cache_dir: Path | None = None,
        session: Session | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> str:
        """Install vanilla Minecraft, the libraries and the version JSON.

        This does nothing if the version is already installed.

        Args:
            game: The game directory.
            java: The Java binary to use. Not used by this loader.
            cache_dir: The cache directory. Not used by this loader.
            session: The session to use. A temporary one is created if omitted.
            progress: Receives updates for each stage.
            cancel: Stops the install.

        Returns:
            The installed version id.

        Raises:
            NetworkError: The metadata service could not be reached.
            UnsupportedError: Mojang does not publish this Minecraft version.
            DownloadError: A file could not be downloaded.
            LockedError: Another install kept the game directory for too long.
            Cancelled: ``cancel`` was triggered.
        """
        if game.has_version(self.expected_id()):
            return self.expected_id()
        lock = file_lock(game.path / GAME_LOCK, cancel=cancel)
        with lock, session_scope(session) as client:
            profile = self.profile(client)
            version_id: str = profile["id"]
            if game.has_version(version_id):
                return version_id
            install_version(
                game, self.minecraft, session=client, progress=progress, cancel=cancel
            )
            download(
                [self._resource(item, game) for item in profile["libraries"]],
                session=client,
                progress=progress,
                cancel=cancel,
                task="libraries",
            )
            game.write_version(version_id, profile)
            return version_id


@register
@dataclass(frozen=True)
class Fabric(MetaLoader):
    """The Fabric loader.

    Attributes:
        meta_url: The base URL of Fabric's metadata service.
    """

    kind: ClassVar[str] = "fabric"
    library: ClassVar[str] = "net.fabricmc:fabric-loader"
    default_maven: ClassVar[str] = "https://maven.fabricmc.net/"
    meta_url: str = "https://meta.fabricmc.net/v2"

    def profile_url(self) -> str:
        """Return where this version's JSON is served."""
        return f"{self.meta_url.rstrip('/')}/versions/loader/{self.minecraft}/{self.version}/profile/json"


@register
@dataclass(frozen=True)
class Quilt(MetaLoader):
    """The Quilt loader.

    Attributes:
        meta_url: The base URL of Quilt's metadata service.
    """

    kind: ClassVar[str] = "quilt"
    library: ClassVar[str] = "org.quiltmc:quilt-loader"
    default_maven: ClassVar[str] = "https://maven.quiltmc.org/repository/release/"
    meta_url: str = "https://meta.quiltmc.org/v3"

    def profile_url(self) -> str:
        """Return where this version's JSON is served."""
        return f"{self.meta_url.rstrip('/')}/versions/loader/{self.minecraft}/{self.version}/profile/json"
