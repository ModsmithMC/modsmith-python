"""The loader interface and the registry behind `create` and `parse`."""

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
    """A specific mod loader version. Subclass it to support another loader.

    Attributes:
        version: The loader version.
        minecraft: The Minecraft version it targets.
        kind: The name it is registered under, such as ``neoforge``.
    """

    version: str
    minecraft: str
    kind: ClassVar[str]

    @abstractmethod
    def version_id(
        self, *, session: Session | None = None, cache_dir: Path | None = None
    ) -> str:
        """Return the id this loader installs under in the ``versions`` directory.

        Args:
            session: The session to use. A temporary one is created if omitted.
            cache_dir: The cache directory. Defaults to the per-user cache.

        Returns:
            The version id.
        """

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
        """Install into ``game`` if needed and return the version id.

        Args:
            game: The game directory.
            java: The Java binary to use, if the loader needs one.
            cache_dir: The cache directory. Defaults to the per-user cache.
            session: The session to use. A temporary one is created if omitted.
            progress: Receives updates for each stage.
            cancel: Stops the install.

        Returns:
            The installed version id.
        """

    def expected_id(self) -> str | None:
        """Return the version id this loader should have, without any network use.

        Returns:
            The version id, or None if it cannot be known in advance. That is
            the default, and `version_id` is used instead.
        """
        return None

    def is_installed(
        self,
        game: GameDir,
        *,
        session: Session | None = None,
        cache_dir: Path | None = None,
    ) -> bool:
        """Return whether this loader is already installed in ``game``.

        The built-in loaders answer this from local files, with no network use.

        Args:
            game: The game directory.
            session: The session to use, if the loader has to ask a service.
            cache_dir: The cache directory. Defaults to the per-user cache.

        Returns:
            True if its version JSON exists.
        """
        expected = self.expected_id()
        if expected is not None:
            return game.has_version(expected)
        return game.has_version(self.version_id(session=session, cache_dir=cache_dir))


_registry: dict[str, type[Loader]] = {}
_aliases = {"fabric-loader": "fabric", "quilt-loader": "quilt"}
# Quilt loads Fabric mods, so a Fabric release can stand in for a Quilt one.
LOADER_FALLBACKS = {"quilt": ("quilt", "fabric")}


def loader_name(kind: str) -> str:
    """Return the name platforms use for a loader, such as ``fabric`` for ``fabric-loader``."""
    name = kind.lower()
    return _aliases.get(name, name)


def register(cls: type[Loader]) -> type[Loader]:
    """Make a `Loader` subclass available to `create` and `parse`.

    It can be used as a class decorator.

    Args:
        cls: The subclass.

    Returns:
        The same subclass.
    """
    _registry[cls.kind] = cls
    return cls


def create(kind: str, version: str, minecraft: str) -> Loader:
    """Build a loader from a name such as ``neoforge`` or ``fabric-loader``.

    Args:
        kind: The loader's name, in any case.
        version: The loader version. A leading ``<minecraft>-`` is removed.
        minecraft: The Minecraft version.

    Returns:
        The loader.

    Raises:
        UnsupportedError: No loader is registered under that name.
    """
    cls = _registry.get(loader_name(kind))
    if cls is None:
        raise UnsupportedError(f"Unsupported mod loader: {kind}")
    return cls(version.removeprefix(f"{minecraft}-"), minecraft)


def parse(loader_id: str, minecraft: str) -> Loader:
    """Build a loader from an id such as ``forge-47.3.0``.

    Args:
        loader_id: The loader's name and version, joined by a hyphen.
        minecraft: The Minecraft version.

    Returns:
        The loader.

    Raises:
        UnsupportedError: The id is malformed or the loader is unknown.
    """
    kind, _, version = loader_id.partition("-")
    if not version:
        raise UnsupportedError(f"Unsupported mod loader: {loader_id}")
    return create(kind, version, minecraft)
