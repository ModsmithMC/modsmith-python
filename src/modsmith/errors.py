"""Exceptions raised by modsmith. All of them derive from `ModsmithError`."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .packs import PackEntry

__all__ = [
    "Cancelled",
    "DownloadError",
    "InstanceError",
    "IntegrityError",
    "JavaError",
    "LauncherError",
    "LoaderError",
    "ModsmithError",
    "NetworkError",
    "PackError",
    "PlatformError",
    "ProcessorError",
    "UnresolvedEntriesError",
    "UnsupportedError",
]


class ModsmithError(Exception):
    """Base class for every error raised by this package."""


class Cancelled(ModsmithError):
    """A `CancelToken` stopped the operation. It can be run again later."""


class NetworkError(ModsmithError):
    """An HTTP request failed.

    Args:
        message: What went wrong.
        status: The HTTP status code.

    Attributes:
        status: The HTTP status code, or None if no response arrived.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DownloadError(ModsmithError):
    """One or more downloads failed.

    Args:
        message: A summary of the failure.
        failures: A reason for each file that failed.

    Attributes:
        failures: A reason for each file that failed.
    """

    def __init__(self, message: str, failures: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.failures = list(failures)


class IntegrityError(ModsmithError):
    """A file does not match its expected size or hash."""


class UnsupportedError(ModsmithError):
    """The requested version, loader or format is not supported."""


class PackError(ModsmithError):
    """A modpack archive is invalid."""


class PlatformError(ModsmithError):
    """A platform could not provide the requested data."""


class LoaderError(ModsmithError):
    """A mod loader could not be installed."""


class ProcessorError(LoaderError):
    """A Forge or NeoForge install processor failed."""


class JavaError(ModsmithError):
    """A Java runtime could not be found or installed."""


class LauncherError(ModsmithError):
    """The launcher profile data could not be used."""


class InstanceError(ModsmithError):
    """A game instance could not be read or changed."""


class UnresolvedEntriesError(InstanceError):
    """A pack still has entries with no download.

    Args:
        entries: The entries that could not be found.

    Attributes:
        entries: The entries that could not be found.
    """

    def __init__(self, entries: "Sequence[PackEntry]") -> None:
        super().__init__(f"{len(entries)} pack entries have no download")
        self.entries = list(entries)
