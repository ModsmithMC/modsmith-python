from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from ..errors import UnsupportedError
from ..minecraft import GameDir
from ..net import Session
from ..progress import CancelToken, ProgressCallback


@dataclass(frozen=True)
class Loader(ABC):
    """A specific mod loader version. Subclass it to support another loader."""

    version: str
    minecraft: str
    kind: ClassVar[str]

    @abstractmethod
    def version_id(
        self, *, session: Session | None = None, cache_dir: Path | None = None
    ) -> str:
        """The id this loader installs under in the `versions` directory."""

    @abstractmethod
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
        """Install into `game` if needed and return the version id."""

    def is_installed(
        self,
        game: GameDir,
        *,
        session: Session | None = None,
        cache_dir: Path | None = None,
    ) -> bool:
        return game.has_version(self.version_id(session=session, cache_dir=cache_dir))


_registry: dict[str, type[Loader]] = {}
_aliases = {"fabric-loader": "fabric", "quilt-loader": "quilt"}


def register(cls: type[Loader]) -> type[Loader]:
    """Make a `Loader` subclass available to `create` and `parse`."""
    _registry[cls.kind] = cls
    return cls


def create(kind: str, version: str, minecraft: str) -> Loader:
    """Build a loader from a name such as `neoforge` or `fabric-loader`."""
    name = kind.lower()
    cls = _registry.get(_aliases.get(name, name))
    if cls is None:
        raise UnsupportedError(f"Unsupported mod loader: {kind}")
    return cls(version.removeprefix(f"{minecraft}-"), minecraft)


def parse(loader_id: str, minecraft: str) -> Loader:
    """Build a loader from an id such as `forge-47.3.0`."""
    kind, _, version = loader_id.partition("-")
    if not version:
        raise UnsupportedError(f"Unsupported mod loader: {loader_id}")
    return create(kind, version, minecraft)
