from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from ..minecraft import GameDir, install_version, maven_path
from ..net import Resource, Session, download
from ..net._session import session_scope
from ..progress import CancelToken, ProgressCallback
from ._base import Loader, register

HASH_FIELDS = ("sha512", "sha256", "sha1", "md5")


@dataclass(frozen=True)
class MetaLoader(Loader):
    """A loader described by a version JSON from a metadata service."""

    meta_url: str = ""
    default_maven: ClassVar[str]

    @abstractmethod
    def profile_url(self) -> str:
        """Where this loader's version JSON is served."""

    def profile(self, session: Session | None = None) -> dict[str, Any]:
        with session_scope(session) as client:
            return client.get_json(self.profile_url())

    def version_id(
        self, *, session: Session | None = None, cache_dir: Path | None = None
    ) -> str:
        return self.profile(session)["id"]

    def _resource(self, library: dict[str, Any], game: GameDir) -> Resource:
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
        with session_scope(session) as client:
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
    kind: ClassVar[str] = "fabric"
    default_maven: ClassVar[str] = "https://maven.fabricmc.net/"
    meta_url: str = "https://meta.fabricmc.net/v2"

    def profile_url(self) -> str:
        return f"{self.meta_url.rstrip('/')}/versions/loader/{self.minecraft}/{self.version}/profile/json"


@register
@dataclass(frozen=True)
class Quilt(MetaLoader):
    kind: ClassVar[str] = "quilt"
    default_maven: ClassVar[str] = "https://maven.quiltmc.org/repository/release/"
    meta_url: str = "https://meta.quiltmc.org/v3"

    def profile_url(self) -> str:
        return f"{self.meta_url.rstrip('/')}/versions/loader/{self.minecraft}/{self.version}/profile/json"
