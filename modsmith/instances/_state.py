"""What an instance records about itself, and the results it reports."""

import json
import time
import zipfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .._fs import write_json
from ..errors import InstanceError
from ..loaders import loader_name
from ..net import file_hash, strongest_hash
from ..packs import FileRef, PackEntry

STATE_DIR = ".modsmith"
STATE_FILE = f"{STATE_DIR}/instance.json"
STAGING_DIR = f"{STATE_DIR}/staging"
BACKUP_DIR = f"{STATE_DIR}/backup"
HASH_CACHE = f"{STATE_DIR}/hashes.json"
LOCK_FILE = f"{STATE_DIR}/lock"
CACHE_SETTLE_NS = 2_000_000_000
# The game skips files with this suffix, which is how launchers switch them off.
DISABLED_SUFFIX = ".disabled"


@dataclass(frozen=True)
class Addition:
    """A project installed on its own, rather than by the instance's pack.

    Attributes:
        entry: The file: its path in the instance, its download and its hashes.
            Its ``ref`` names the platform, project and release.
        name: The project's display name.
        slug: The project's short name.
        project_type: The kind of project, such as ``mod`` or ``shader``.
        sha1: The file's hash when it was installed. A different hash means the
            player changed it.
        requested: Whether it was asked for, rather than installed because
            another addition needs it.
        requires: The ids of the projects it needs.
        pinned: Whether `Instance.plan_updates` leaves it at this release.
    """

    entry: PackEntry
    name: str
    slug: str = ""
    project_type: str = "mod"
    sha1: str = ""
    requested: bool = True
    requires: tuple[str, ...] = ()
    pinned: bool = False

    @property
    def path(self) -> str:
        """Where the file goes, relative to the instance."""
        return self.entry.path or ""

    @property
    def platform(self) -> str:
        """The name of the platform it came from."""
        return self.entry.ref.platform if self.entry.ref else ""

    @property
    def project_id(self) -> str:
        """The project's id on its platform."""
        return self.entry.ref.project_id if self.entry.ref else ""

    @property
    def release_id(self) -> str:
        """The installed release's id on its platform."""
        return self.entry.ref.file_id if self.entry.ref else ""

    def matches(self, name: str) -> bool:
        """Return whether ``name`` is this addition's project id, slug or path."""
        return name in (self.project_id, self.slug, self.path)


@dataclass(frozen=True)
class InstanceState:
    """What an instance holds, as of its last change.

    Attributes:
        minecraft: The Minecraft version.
        loader_kind: The mod loader's name as platforms use it, such as
            ``fabric``, or None for vanilla.
        loader_version: The mod loader's version, or None if unknown.
        pack_name: The pack's name, or None if no pack was synced.
        pack_version: The pack's version, or None if no pack was synced.
        files: The SHA-1 of each file the pack installed, keyed by path.
        kept: The paths where the player's version was kept.
        additions: The projects installed on their own.
        pack_refs: The platform files the pack installed, so additions can
            tell which projects it already provides.
        synced_at: When the instance last changed, in ISO 8601 format.
    """

    minecraft: str
    loader_kind: str | None = None
    loader_version: str | None = None
    pack_name: str | None = None
    pack_version: str | None = None
    files: dict[str, str] = field(default_factory=dict[str, str])
    kept: tuple[str, ...] = ()
    additions: tuple[Addition, ...] = ()
    pack_refs: tuple[FileRef, ...] = ()
    synced_at: str = ""


@dataclass(frozen=True)
class Changes:
    """What a change to an instance would do, or did.

    Each field holds paths relative to the instance.

    Attributes:
        added: New files.
        updated: Files that are replaced.
        removed: Files that are no longer wanted.
        unchanged: Files that already match.
        conflicts: Files that would be replaced but that the player changed.
            They are kept unless ``overwrite`` is set.
        orphaned: Files that are no longer wanted but that the player changed.
            They are kept.
        unresolved: Entries that have no download.
        superseded: Additions that the pack now provides. The pack's file
            replaces them.
    """

    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    unresolved: tuple[PackEntry, ...] = ()
    superseded: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContentFile:
    """A mod, resource pack or shader pack in an instance.

    Attributes:
        path: Its path relative to the instance, without the ``.disabled``
            suffix. Resource and shader packs can be folders.
        enabled: False if it carries the ``.disabled`` suffix, so the game
            skips it.
        source: ``pack`` if the pack installed it, ``addition`` if it was added
            on its own, and ``user`` if the player put it there.
        addition: The addition, if it is one.
    """

    path: str
    enabled: bool = True
    source: Literal["pack", "addition", "user"] = "user"
    addition: Addition | None = None

    @property
    def location(self) -> str:
        """Its actual path relative to the instance, with any suffix."""
        return self.path if self.enabled else self.path + DISABLED_SUFFIX


def _entry(data: dict[str, Any]) -> PackEntry:
    """Rebuild a `PackEntry` from its saved form."""
    ref = data.get("ref")
    return PackEntry(
        path=data.get("path"),
        urls=tuple(data.get("urls", ())),
        hashes=dict(data.get("hashes", {})),
        size=data.get("size"),
        client=data.get("client", "required"),
        server=data.get("server", "required"),
        ref=FileRef(**ref) if ref else None,
        manual_url=data.get("manual_url"),
    )


def _addition(data: dict[str, Any]) -> Addition:
    """Rebuild an `Addition` from its saved form."""
    return Addition(
        entry=_entry(data["entry"]),
        name=data["name"],
        slug=data.get("slug", ""),
        project_type=data.get("project_type", "mod"),
        sha1=data.get("sha1", ""),
        requested=data.get("requested", True),
        requires=tuple(data.get("requires", ())),
        pinned=data.get("pinned", False),
    )


def read_state(path: Path) -> InstanceState | None:
    """Read a state file, or return None if there is none.

    Raises:
        InstanceError: The file is corrupt.
    """
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        data["kept"] = tuple(data.get("kept", ()))
        # Version 0.2 kept the pack's own name, such as ``fabric-loader``.
        if data.get("loader_kind"):
            data["loader_kind"] = loader_name(data["loader_kind"])
        data["additions"] = tuple(_addition(item) for item in data.get("additions", ()))
        data["pack_refs"] = tuple(FileRef(**item) for item in data.get("pack_refs", ()))
        return InstanceState(**data)
    except (ValueError, TypeError, KeyError) as e:
        raise InstanceError(f"Corrupt instance state in {path.parent}: {e}") from e


def write_state(path: Path, state: InstanceState) -> None:
    """Write a state file."""
    write_json(path, asdict(state))


class HashCache:
    """Hashes of an instance's files, so unchanged files are not read again.

    A file counts as unchanged while its size and modification time are the
    same. Files changed moments before saving are left out, because another
    change could land on the same timestamp.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / HASH_CACHE
        self.files: dict[str, dict[str, Any]] = {}
        self.overrides: dict[str, list[Any]] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.files = dict(data["files"])
            self.overrides = dict(data["overrides"])
        except (OSError, ValueError, KeyError, TypeError):
            self.files = {}
            self.overrides = {}

    def digest(self, relative: str, algorithm: str = "sha1") -> str:
        """Return a file's hash, reading the file only if it has changed."""
        path = self.root / relative
        stat = path.stat()
        entry: dict[str, Any] | None = self.files.get(relative)
        if (
            entry is None
            or entry.get("size") != stat.st_size
            or entry.get("mtime_ns") != stat.st_mtime_ns
        ):
            entry = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            self.files[relative] = entry
        if algorithm not in entry:
            entry[algorithm] = file_hash(path, algorithm)
        return entry[algorithm]

    def matches(self, relative: str, hashes: Mapping[str, str]) -> bool:
        """Check a file against its strongest hash."""
        expected = strongest_hash(hashes)
        return expected is None or self.digest(relative, expected[0]) == expected[1]

    def override_sha1(self, relative: str, info: zipfile.ZipInfo) -> str | None:
        """Return the known hash of an override, or None if it has changed."""
        entry = self.overrides.get(relative)
        if entry is None or entry[:2] != [info.CRC, info.file_size]:
            return None
        return entry[2]

    def remember_override(
        self, relative: str, info: zipfile.ZipInfo, digest: str
    ) -> None:
        """Record the hash of an override."""
        self.overrides[relative] = [info.CRC, info.file_size, digest]

    def save(self) -> None:
        """Write the cache, leaving out files that changed moments ago."""
        settled = time.time_ns() - CACHE_SETTLE_NS
        files = {
            relative: entry
            for relative, entry in self.files.items()
            if entry["mtime_ns"] < settled
        }
        write_json(self.path, {"files": files, "overrides": self.overrides})
