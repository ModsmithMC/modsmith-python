"""Loaders installed by running processors: Forge and NeoForge."""

import logging
import re
import tempfile
import xml.etree.ElementTree as ElementTree
from abc import abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self

from .. import java as java_runtime
from .._locks import GAME_LOCK, file_lock
from .._paths import default_cache_dir
from ..errors import JavaError, LoaderError, NetworkError, ProcessorError
from ..minecraft import GameDir, Version, install_version
from ..net import Resource, Session, download
from ..net._session import session_scope
from ..progress import CancelToken, ProgressCallback
from ._base import (
    Loader,
    LoaderVersion,
    game_argument,
    is_stable,
    library_versions,
    recommend,
    register,
)
from ._install_profile import InstallerJar, Library, Variables
from ._processors import run_processors

logger = logging.getLogger(__name__)
LEGACY_NEOFORGE = "1.20.1"
FORGE_PROMOTIONS = (
    "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
)
# Forge installers for older versions work differently and are not supported.
FIRST_SUPPORTED = (1, 13)
# Every NeoForge library is published under this Maven group.
NEOFORGE_GROUP = "net.neoforged"


def maven_versions(session: Session, url: str) -> list[str]:
    """Read the versions listed in a Maven ``maven-metadata.xml``.

    Raises:
        NetworkError: The file could not be fetched or is not valid XML.
    """
    text = session.request("GET", url).text
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as e:
        raise NetworkError(f"Invalid Maven metadata from {url}: {e}") from e
    return [item.text for item in root.iter("version") if item.text]


def neoforge_minecraft(version: str) -> str | None:
    """Return the Minecraft version that a NeoForge version is for.

    NeoForge numbers its versions after the game: ``21.1.77`` is for 1.21.1
    and ``21.0.143`` for 1.21. From 2026 the game's own version comes first,
    so ``26.1.2.125`` is for 26.1.2 and ``26.3.0.100`` for 26.3.

    Returns:
        The Minecraft version, or None if the version does not follow either
        scheme.
    """
    numbers = version.split("-")[0].split(".")
    if len(numbers) < 3 or not all(part.isdigit() for part in numbers):
        return None
    if len(numbers) >= 4:
        game = numbers[:3]
        return ".".join(game[:2] if game[2] == "0" else game)
    major, minor = numbers[0], numbers[1]
    return f"1.{major}" if minor == "0" else f"1.{major}.{minor}"


def _before_1_13(minecraft: str) -> bool:
    """Return whether a release such as ``1.12.2`` predates Minecraft 1.13."""
    match = re.match(r"(\d+)\.(\d+)", minecraft)
    return match is not None and (int(match[1]), int(match[2])) < FIRST_SUPPORTED


@dataclass(frozen=True)
class ProcessorLoader(Loader):
    """A loader installed by patching Minecraft with processor jars.

    Attributes:
        repository: The Maven repository that hosts the installers.
        java_index_url: Where to read Mojang's runtime index.
    """

    repository: str = ""
    java_index_url: str = java_runtime.RUNTIME_INDEX_URL

    @abstractmethod
    def installer_url(self) -> str:
        """Return where this version's installer jar is published."""

    def _fetch_installer(
        self, *, session: Session | None = None, cache_dir: Path | None = None
    ) -> InstallerJar:
        """Return this version's installer, downloading it if it is not cached.

        The download is checked against the published SHA-1 when there is one.

        Args:
            session: The session to use. A temporary one is created if omitted.
            cache_dir: The cache directory. Defaults to the per-user cache.

        Returns:
            The installer.

        Raises:
            DownloadError: The installer could not be downloaded.
            LoaderError: The installer is malformed.
            LockedError: Another process kept the download for too long.
            UnsupportedError: The installer is older than Minecraft 1.13.
        """
        url = self.installer_url()
        dest = (cache_dir or default_cache_dir()) / "installers" / url.rsplit("/", 1)[1]
        if not dest.is_file():
            lock = file_lock(dest.with_name(f"{dest.name}.lock"))
            with lock, session_scope(session) as client:
                if not dest.is_file():
                    try:
                        body = client.request("GET", f"{url}.sha1").text
                        hashes = {"sha1": body.split()[0]}
                    except (NetworkError, IndexError):
                        hashes = None
                    download(Resource.of(url, dest, hashes), session=client)
        return InstallerJar(dest)

    def version_id(
        self, *, session: Session | None = None, cache_dir: Path | None = None
    ) -> str:
        """Return the id declared by the installer, downloading it if needed.

        Args:
            session: The session to use. A temporary one is created if omitted.
            cache_dir: The cache directory. Defaults to the per-user cache.

        Returns:
            The version id.

        Raises:
            DownloadError: The installer could not be downloaded.
            LoaderError: The installer is malformed.
            UnsupportedError: The installer is older than Minecraft 1.13.
        """
        return self._fetch_installer(session=session, cache_dir=cache_dir).version_id

    def _resource(self, library: Library, game: GameDir) -> Resource | None:
        """Describe a library's download, or None if the installer provided it."""
        dest = game.libraries_dir / library.path
        if library.url is None and dest.is_file():
            return None
        url = library.url or f"{self.repository.rstrip('/')}/{library.path}"
        return Resource.of(url, dest, library.hashes, library.size)

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
        """Install vanilla Minecraft, the libraries and the patched game files.

        The version is registered last, so a failed install leaves no broken version
        behind. This does nothing if the version is already installed.

        Args:
            game: The game directory.
            java: The Java binary to use. By default, installed runtimes are tried
                first, then runtimes downloaded from Mojang. ``jre-legacy`` is
                the last choice.
            cache_dir: The cache directory. Defaults to the per-user cache.
            session: The session to use. A temporary one is created if omitted.
            progress: Receives updates for each stage.
            cancel: Stops the install.

        Returns:
            The installed version id.

        Raises:
            LoaderError: The installer is malformed or targets another Minecraft
                version.
            ProcessorError: A processor failed.
            JavaError: No usable Java runtime could be found or downloaded.
            UnsupportedError: The version is not supported.
            NetworkError: Mojang's version manifest could not be fetched.
            DownloadError: A file could not be downloaded.
            LockedError: Another install kept the game directory for too long.
            Cancelled: ``cancel`` was triggered.
        """
        expected = self.expected_id()
        if expected is not None and game.has_version(expected):
            return expected
        if cache_dir is not None:
            cache_dir = Path(cache_dir).resolve()  # processors run in another directory
        lock = file_lock(game.path / GAME_LOCK, cancel=cancel)
        with lock, session_scope(session) as client:
            installer = self._fetch_installer(session=client, cache_dir=cache_dir)
            if game.has_version(installer.version_id):
                return installer.version_id
            if installer.profile.minecraft != self.minecraft:
                raise LoaderError(
                    f"Installer targets Minecraft {installer.profile.minecraft}"
                )

            install_version(
                game, self.minecraft, session=client, progress=progress, cancel=cancel
            )
            installer.extract_bundled_libraries(game.libraries_dir)
            libraries = [
                *installer.profile.libraries,
                # Entries with no URL are processor outputs, which cannot be downloaded.
                *(item for item in installer.version_libraries if item.url),
            ]
            resources = [self._resource(item, game) for item in libraries]
            download(
                [item for item in resources if item],
                session=client,
                progress=progress,
                cancel=cancel,
                task="libraries",
            )
            self._patch(installer, game, java, cache_dir, client, progress, cancel)
            game.write_version(installer.version_id, installer.version_json)
            return installer.version_id

    def _patch(
        self,
        installer: InstallerJar,
        game: GameDir,
        java: Path | None,
        cache_dir: Path | None,
        session: Session,
        progress: ProgressCallback | None,
        cancel: CancelToken | None,
    ) -> None:
        """Run the client processors, trying Java runtimes until one works."""
        processors = installer.profile.client_processors()
        if not processors:
            return
        with tempfile.TemporaryDirectory(prefix="modsmith-installer-") as temp:
            variables = Variables.build(
                installer,
                game.libraries_dir,
                game.path,
                game.client_jar(self.minecraft),
                Path(temp),
            )

            def attempt(executable: Path) -> None:
                run_processors(
                    processors,
                    variables,
                    executable,
                    game.libraries_dir,
                    progress,
                    cancel,
                )

            if java is not None:
                attempt(java)
                return

            failure: ProcessorError | None = None
            runtimes = self._runtimes(game, cache_dir, session, progress, cancel)
            for runtime in runtimes:
                try:
                    attempt(runtime.executable)
                    return
                except ProcessorError as e:
                    failure = e
                    logger.warning("Processors failed on %s: %s", runtime.component, e)
            raise failure or JavaError(f"No usable Java runtime for {self.minecraft}")

    def _runtimes(
        self,
        game: GameDir,
        cache_dir: Path | None,
        session: Session,
        progress: ProgressCallback | None,
        cancel: CancelToken | None,
    ) -> Iterator[java_runtime.JavaRuntime]:
        """Yield Java runtimes to try, installed ones first and downloads after.

        Processors are install tools, so they do not need the Java that the game
        runs on. ``jre-legacy`` is the last choice, because Mojang's Windows build
        breaks some installs and there is no build for Apple Silicon.
        """
        required = java_runtime.required_for(game.version(self.minecraft), game)
        legacy = required == java_runtime.LEGACY_COMPONENT
        exact = java_runtime.find(required, game=game, cache_dir=cache_dir)
        installed = java_runtime.find_all(game=game, cache_dir=cache_dir)
        tried: set[str] = set()
        for runtime in [*([] if legacy or exact is None else [exact]), *installed]:
            if runtime.component not in tried:
                tried.add(runtime.component)
                yield runtime

        fallback = java_runtime.FALLBACK_COMPONENT
        for component in [fallback, required] if legacy else [required, fallback]:
            if component in tried:
                continue
            tried.add(component)
            try:
                runtime = java_runtime.download(
                    component,
                    cache_dir=cache_dir,
                    session=session,
                    progress=progress,
                    cancel=cancel,
                    index_url=self.java_index_url,
                )
            except JavaError as e:
                logger.warning("Cannot use %s: %s", component, e)
                continue
            yield runtime


@register
@dataclass(frozen=True)
class Forge(ProcessorLoader):
    """The Forge loader, for Minecraft 1.13 and later.

    Attributes:
        repository: The Maven repository that hosts the installers.
    """

    kind: ClassVar[str] = "forge"
    repository: str = "https://maven.minecraftforge.net"

    @classmethod
    def available(
        cls,
        minecraft: str,
        *,
        session: Session | None = None,
        repository: str | None = None,
        promotions_url: str = FORGE_PROMOTIONS,
    ) -> list[LoaderVersion]:
        """List Forge's versions for a Minecraft version, newest first.

        The recommended version is the one Forge itself recommends for that
        Minecraft version, or the newest when it recommends none.

        Args:
            minecraft: The Minecraft version.
            session: The session to use. A temporary one is created if omitted.
            repository: The Maven repository. Defaults to Forge's own.
            promotions_url: Where Forge lists its recommended versions.

        Returns:
            The versions, empty if Forge has none for that Minecraft version,
            or if it is older than 1.13, whose installers are not supported.

        Raises:
            NetworkError: The version list could not be fetched.
        """
        if _before_1_13(minecraft):
            return []
        base = (repository or cls.repository).rstrip("/")
        with session_scope(session) as client:
            names = maven_versions(
                client, f"{base}/net/minecraftforge/forge/maven-metadata.xml"
            )
            promotions: dict[str, str] = client.get_json(promotions_url).get(
                "promos", {}
            )
        prefix = f"{minecraft}-"
        found = [
            LoaderVersion(cls.kind, name.removeprefix(prefix), minecraft)
            for name in names
            if name.startswith(prefix)
        ]
        return recommend(found, promotions.get(f"{minecraft}-recommended"))

    @classmethod
    def from_version(cls, version: Version, minecraft: str) -> Self | None:
        """Recognise Forge by the version it passes the game, or its library.

        NeoForge for 1.20.1 started as a copy of Forge and passes the same
        argument, so a version with NeoForge's libraries is left to NeoForge.
        """
        libraries = library_versions(version)
        if any(name.startswith(NEOFORGE_GROUP) for name in libraries):
            return None
        found = game_argument(version, "--fml.forgeVersion") or libraries.get(
            "net.minecraftforge:forge"
        )
        return cls(found.removeprefix(f"{minecraft}-"), minecraft) if found else None

    def expected_id(self) -> str:
        """Return the version id that this version's installer declares."""
        return f"{self.minecraft}-forge-{self.version}"

    def installer_url(self) -> str:
        """Return where this version's installer jar is published."""
        version = f"{self.minecraft}-{self.version}"
        return f"{self.repository.rstrip('/')}/net/minecraftforge/forge/{version}/forge-{version}-installer.jar"


@register
@dataclass(frozen=True)
class NeoForge(ProcessorLoader):
    """The NeoForge loader.

    Attributes:
        repository: The Maven repository that hosts the installers.
    """

    kind: ClassVar[str] = "neoforge"
    repository: str = "https://maven.neoforged.net/releases"

    @classmethod
    def from_version(cls, version: Version, minecraft: str) -> Self | None:
        """Recognise NeoForge by the version it passes the game, or its library."""
        found = game_argument(version, "--fml.neoForgeVersion")
        libraries = library_versions(version)
        if found is None and any(name.startswith(NEOFORGE_GROUP) for name in libraries):
            found = game_argument(version, "--fml.forgeVersion") or libraries.get(
                "net.neoforged:forge"
            )
        return cls(found.removeprefix(f"{minecraft}-"), minecraft) if found else None

    @classmethod
    def available(
        cls,
        minecraft: str,
        *,
        session: Session | None = None,
        repository: str | None = None,
    ) -> list[LoaderVersion]:
        """List NeoForge's versions for a Minecraft version, newest first.

        NeoForge publishes one unsorted list for every Minecraft version, so the
        game version is worked out from each version number. Versions marked
        ``beta`` are pre-releases, and the newest stable one is recommended.

        Args:
            minecraft: The Minecraft version.
            session: The session to use. A temporary one is created if omitted.
            repository: The Maven repository. Defaults to NeoForge's own.

        Returns:
            The versions, empty if NeoForge has none for that Minecraft version.

        Raises:
            NetworkError: The version list could not be fetched.
        """
        base = (repository or cls.repository).rstrip("/")
        with session_scope(session) as client:
            # NeoForge's first release still used Forge's artifact name.
            if minecraft == LEGACY_NEOFORGE:
                url = f"{base}/net/neoforged/forge/maven-metadata.xml"
                prefix = f"{minecraft}-"
                names = [
                    name.removeprefix(prefix)
                    for name in maven_versions(client, url)
                    if name.startswith(prefix)
                ]
            else:
                url = f"{base}/net/neoforged/neoforge/maven-metadata.xml"
                names = [
                    name
                    for name in maven_versions(client, url)
                    if neoforge_minecraft(name) == minecraft
                ]
        found = [
            LoaderVersion(cls.kind, name, minecraft, is_stable(name)) for name in names
        ]
        return recommend(found)

    def expected_id(self) -> str:
        """Return the version id that this version's installer declares."""
        if self.minecraft == LEGACY_NEOFORGE:
            return f"{self.minecraft}-forge-{self.version}"
        return f"neoforge-{self.version}"

    def installer_url(self) -> str:
        """Return where this version's installer jar is published."""
        base = self.repository.rstrip("/")
        # NeoForge's first release still used Forge's artifact name.
        if self.minecraft == LEGACY_NEOFORGE:
            version = f"{self.minecraft}-{self.version}"
            return f"{base}/net/neoforged/forge/{version}/forge-{version}-installer.jar"
        return f"{base}/net/neoforged/neoforge/{self.version}/neoforge-{self.version}-installer.jar"
