"""The loader interface and the registry behind `create` and `parse`."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from ..errors import UnsupportedError
from ..minecraft import GameDir
from ..net import Session
from ..progress import CancelToken, ProgressCallback

# Words in a version that mark a pre-release, such as ``0.20.0-beta.9``.
PRE_RELEASE = re.compile(r"(alpha|beta|pre|rc)", re.IGNORECASE)


def version_key(version: str) -> tuple[tuple[int, ...], bool, str]:
    """Sort key for loader versions: numbers first, then releases after pre-releases."""
    numbers = tuple(int(part) for part in re.findall(r"\d+", version.split("-")[0]))
    return numbers, not PRE_RELEASE.search(version), version


def is_stable(version: str) -> bool:
    """Return whether a version's text marks it as a full release."""
    return not PRE_RELEASE.search(version)


@dataclass(frozen=True)
class LoaderVersion:
    """One published version of a mod loader for a Minecraft version.

    Attributes:
        kind: The loader's name, such as ``fabric``.
        version: The loader version.
        minecraft: The Minecraft version it targets.
        stable: Whether it is a full release rather than an alpha or beta.
        recommended: Whether it is the one to install by default. At most one
            version in a list is recommended.
    """

    kind: str
    version: str
    minecraft: str
    stable: bool = True
    recommended: bool = False

    def loader(self) -> "Loader":
        """Return a loader for this version, ready to install.

        Raises:
            UnsupportedError: No loader is registered under ``kind``.
        """
        return create(self.kind, self.version, self.minecraft)


def recommend(
    versions: list[LoaderVersion], choice: str | None = None
) -> list[LoaderVersion]:
    """Sort versions newest first and mark the one to install by default.

    Args:
        versions: The versions, in any order.
        choice: The version the loader's own project recommends, if it names one
            and it is in the list. Otherwise the newest stable version is chosen.

    Returns:
        The sorted versions.
    """
    ordered = sorted(versions, key=lambda item: version_key(item.version), reverse=True)
    known = {item.version for item in ordered}
    if choice not in known:
        choice = next((item.version for item in ordered if item.stable), None)
    return [
        LoaderVersion(
            item.kind, item.version, item.minecraft, item.stable, item.version == choice
        )
        for item in ordered
    ]


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

    @classmethod
    def available(
        cls, minecraft: str, *, session: Session | None = None
    ) -> list[LoaderVersion]:
        """List this loader's versions for a Minecraft version, newest first.

        Override it so `versions` and `recommended` can offer the loader.

        Args:
            minecraft: The Minecraft version.
            session: The session to use. A temporary one is created if omitted.

        Returns:
            The versions, empty if the loader does not support that Minecraft
            version. At most one is marked recommended.

        Raises:
            UnsupportedError: The loader cannot list its versions. That is the
                default.
            NetworkError: The loader's version list could not be fetched.
        """
        raise UnsupportedError(f"{cls.kind} cannot list its versions")

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
    cls = _loader_class(kind)
    return cls(version.removeprefix(f"{minecraft}-"), minecraft)


def _loader_class(kind: str) -> type[Loader]:
    """Return the class registered under a loader name."""
    cls = _registry.get(loader_name(kind))
    if cls is None:
        raise UnsupportedError(f"Unsupported mod loader: {kind}")
    return cls


def versions(
    kind: str, minecraft: str, *, session: Session | None = None
) -> list[LoaderVersion]:
    """List a loader's versions for a Minecraft version, newest first.

    Each loader publishes its versions differently. This reads each one's own
    source and returns the same shape for all of them.

    Args:
        kind: The loader's name, such as ``neoforge`` or ``fabric-loader``.
        minecraft: The Minecraft version.
        session: The session to use. A temporary one is created if omitted.

    Returns:
        The versions, empty if the loader does not support that Minecraft
        version. At most one is marked recommended.

    Raises:
        UnsupportedError: The loader is unknown or cannot list its versions.
        NetworkError: The version list could not be fetched.
    """
    return _loader_class(kind).available(minecraft, session=session)


def recommended(kind: str, minecraft: str, *, session: Session | None = None) -> Loader:
    """Return the loader version to install by default for a Minecraft version.

    That is the version the loader's project recommends, if it names one, and
    otherwise its newest stable version. If there is no stable version, the
    newest one is used.

    Args:
        kind: The loader's name.
        minecraft: The Minecraft version.
        session: The session to use. A temporary one is created if omitted.

    Returns:
        The loader, ready to install.

    Raises:
        UnsupportedError: The loader is unknown, cannot list its versions, or
            has none for that Minecraft version.
        NetworkError: The version list could not be fetched.
    """
    found = versions(kind, minecraft, session=session)
    choice = next((item for item in found if item.recommended), None)
    if choice is None and found:
        choice = found[0]
    if choice is None:
        raise UnsupportedError(f"{kind} has no version for Minecraft {minecraft}")
    return choice.loader()


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
