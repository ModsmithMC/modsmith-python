import logging
import tempfile
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .. import java as java_runtime
from .._support import default_cache_dir
from ..errors import JavaError, LoaderError, NetworkError, ProcessorError
from ..minecraft import GameDir, install_version
from ..net import Resource, Session, download
from ..net._session import session_scope
from ..progress import CancelToken, ProgressCallback
from ._base import Loader, register
from ._install_profile import InstallerJar, Library, Variables
from ._processors import run_processors

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessorLoader(Loader):
    """A loader installed by patching Minecraft with processor jars."""

    repository: str = ""
    java_index_url: str = java_runtime.RUNTIME_INDEX_URL

    @abstractmethod
    def installer_url(self) -> str:
        """Where this version's installer jar is published."""

    def fetch_installer(
        self, *, session: Session | None = None, cache_dir: Path | None = None
    ) -> InstallerJar:
        url = self.installer_url()
        dest = (cache_dir or default_cache_dir()) / "installers" / url.rsplit("/", 1)[1]
        if not dest.is_file():
            with session_scope(session) as client:
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
        return self.fetch_installer(session=session, cache_dir=cache_dir).version_id

    def _resource(self, library: Library, game: GameDir) -> Resource | None:
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
        if cache_dir is not None:
            cache_dir = Path(cache_dir).resolve()  # processors run in another directory
        with session_scope(session) as client:
            installer = self.fetch_installer(session=client, cache_dir=cache_dir)
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

            component = java_runtime.required_for(game.version(self.minecraft), game)
            exact = java_runtime.find(component, game=game, cache_dir=cache_dir)
            candidates = (
                [exact]
                if exact
                else java_runtime.find_all(game=game, cache_dir=cache_dir)
            )
            failure: ProcessorError | None = None
            for runtime in candidates:
                try:
                    attempt(runtime.executable)
                    return
                except ProcessorError as e:
                    failure = e
                    logger.warning("Processors failed on %s: %s", runtime.component, e)
            if exact and failure:
                raise failure
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
                raise (failure or e) from e
            attempt(runtime.executable)


@register
@dataclass(frozen=True)
class Forge(ProcessorLoader):
    kind: ClassVar[str] = "forge"
    repository: str = "https://maven.minecraftforge.net"

    def installer_url(self) -> str:
        version = f"{self.minecraft}-{self.version}"
        return f"{self.repository.rstrip('/')}/net/minecraftforge/forge/{version}/forge-{version}-installer.jar"


@register
@dataclass(frozen=True)
class NeoForge(ProcessorLoader):
    kind: ClassVar[str] = "neoforge"
    repository: str = "https://maven.neoforged.net/releases"

    def installer_url(self) -> str:
        base = self.repository.rstrip("/")
        if self.minecraft == "1.20.1":
            version = f"{self.minecraft}-{self.version}"
            return f"{base}/net/neoforged/forge/{version}/forge-{version}-installer.jar"
        return f"{base}/net/neoforged/neoforge/{self.version}/neoforge-{self.version}-installer.jar"
