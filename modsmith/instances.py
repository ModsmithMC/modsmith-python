"""Game directories managed from a modpack.

`Instance.sync` is both install and update: it brings a directory to the state
a pack describes, tracks what it wrote, and leaves the user's changes alone.
"""

import json
import shutil
import time
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._locks import file_lock
from ._support import replace_file, write_atomic, write_json
from .errors import InstanceError, UnresolvedEntriesError
from .net import Session, download, file_hash
from .net._resource import matches, stream_hash, strongest_hash
from .net._session import session_scope
from .packs import Modpack, PackEntry, Side
from .progress import CancelToken, ProgressCallback, report

__all__ = ["Changes", "Instance", "InstanceState"]

STATE_DIR = ".modsmith"
STATE_FILE = f"{STATE_DIR}/instance.json"
STAGING_DIR = f"{STATE_DIR}/staging"
BACKUP_DIR = f"{STATE_DIR}/backup"
HASH_CACHE = f"{STATE_DIR}/hashes.json"
LOCK_FILE = f"{STATE_DIR}/lock"
CACHE_SETTLE_NS = 2_000_000_000


@dataclass(frozen=True)
class InstanceState:
    """What the last sync installed.

    Attributes:
        pack_name: The pack's name.
        pack_version: The pack's version.
        minecraft: The Minecraft version.
        loader_kind: The mod loader's name.
        loader_version: The mod loader's version.
        files: The SHA-1 of each file the pack installed, keyed by path.
        kept: The paths where the player's version was kept.
        synced_at: When the sync finished, in ISO 8601 format.
    """

    pack_name: str
    pack_version: str
    minecraft: str
    loader_kind: str
    loader_version: str
    files: dict[str, str] = field(default_factory=dict[str, str])
    kept: tuple[str, ...] = ()
    synced_at: str = ""


@dataclass(frozen=True)
class Changes:
    """What a sync would do, or did. Each field holds paths relative to the instance.

    Attributes:
        added: Files the pack adds.
        updated: Files the pack replaces.
        removed: Files the pack no longer has.
        unchanged: Files that already match.
        conflicts: Files the pack changes that the player also changed. They are
            kept unless ``overwrite`` is set.
        orphaned: Files the pack no longer has that the player changed. They are
            kept.
        unresolved: Pack entries that have no download.
    """

    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    unresolved: tuple[PackEntry, ...] = ()


@dataclass(frozen=True)
class _Target:
    """What one path should contain after a sync."""

    hashes: Mapping[str, str]
    entry: PackEntry | None = None
    override: bool = False


def _targets(
    pack: Modpack, side: Side, include_optional: bool, cache: "_HashCache"
) -> tuple[dict[str, _Target], tuple[PackEntry, ...]]:
    """Return what a pack wants on disk, and its unresolved entries."""
    targets: dict[str, _Target] = {}
    unresolved: list[PackEntry] = []
    for entry in pack.entries:
        if not entry.wanted(side, include_optional):
            continue
        if not entry.is_resolved:
            unresolved.append(entry)
        if entry.path:
            targets[entry.path] = _Target(entry.hashes, entry=entry)
    members = pack.override_members(side)
    unknown = {
        relative: info
        for relative, info in members.items()
        if cache.override_sha1(relative, info) is None
    }
    for relative, file in pack.iter_override_files(side, unknown):
        cache.remember_override(relative, unknown[relative], stream_hash(file))
    for relative, info in members.items():
        digest = cache.override_sha1(relative, info)
        targets[relative] = _Target({"sha1": digest or ""}, override=True)
    return targets, tuple(unresolved)


class _HashCache:
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


def _find_adoptable(
    entries: Iterable[PackEntry], folders: list[Path]
) -> dict[str, Path]:
    """Find manually downloaded files by name, keeping those with the right hash."""
    found: dict[str, Path] = {}
    for entry in entries:
        if entry.path is None:
            continue
        name = Path(entry.path).name
        for folder in folders:
            candidate = folder / name
            if candidate.is_file() and matches(candidate, entry.hashes):
                found[entry.path] = candidate
                break
    return found


def _move(source: Path, dest: Path) -> None:
    """Move a file, creating the destination's parent directories."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    replace_file(source, dest)


class Instance:
    """A game directory whose contents come from a modpack.

    Args:
        path: The directory. It is created by the first sync.

    Attributes:
        path: The directory.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @classmethod
    def open(cls, path: Path | str) -> "Instance":
        """Return the instance at ``path``, which does not have to exist yet."""
        return cls(path)

    def __repr__(self) -> str:
        return f"Instance({str(self.path)!r})"

    @property
    def _state_path(self) -> Path:
        """The file that records the last sync."""
        return self.path / STATE_FILE

    @property
    def _lock_path(self) -> Path:
        """The file that keeps two syncs out of this directory."""
        return self.path / LOCK_FILE

    @property
    def _staging_dir(self) -> Path:
        """Where new files wait until every one of them is ready."""
        return self.path / STAGING_DIR

    @property
    def _backup_dir(self) -> Path:
        """Where replaced files wait until a commit has finished."""
        return self.path / BACKUP_DIR

    @property
    def state(self) -> InstanceState | None:
        """What the last sync installed, or None if nothing has been synced here.

        Raises:
            InstanceError: The state file is corrupt.
        """
        path = self._state_path
        if not path.is_file():
            return None
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            data["kept"] = tuple(data.get("kept", ()))
            return InstanceState(**data)
        except (ValueError, TypeError) as e:
            raise InstanceError(f"Corrupt instance state in {self.path}: {e}") from e

    def diff(
        self, pack: Modpack, *, side: Side = "client", include_optional: bool = False
    ) -> Changes:
        """Compare this directory with a pack. Changes nothing.

        Args:
            pack: The modpack.
            side: The side to install.
            include_optional: Include the pack's optional files.

        Returns:
            What a sync would do.

        Raises:
            InstanceError: The state file is corrupt.
        """
        cache = _HashCache(self.path)
        targets, unresolved = _targets(pack, side, include_optional, cache)
        return self._classify(targets, unresolved, cache)

    def _classify(
        self,
        targets: dict[str, _Target],
        unresolved: tuple[PackEntry, ...],
        cache: _HashCache,
    ) -> Changes:
        """Sort each target and previously installed file into `Changes`."""
        state = self.state
        managed = state.files if state else {}
        added: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        conflicts: list[str] = []
        for relative, target in targets.items():
            dest = self.path / relative
            if not dest.is_file():
                added.append(relative)
            elif cache.matches(relative, target.hashes):
                unchanged.append(relative)
            # With no state, or a file as we left it, the player did not edit it.
            elif state is None or cache.digest(relative) == managed.get(relative):
                updated.append(relative)
            else:
                conflicts.append(relative)

        removed: list[str] = []
        orphaned: list[str] = []
        for relative, expected in managed.items():
            dest = self.path / relative
            if relative in targets or not dest.is_file():
                continue
            unedited = cache.digest(relative) == expected
            (removed if unedited else orphaned).append(relative)
        return Changes(
            tuple(added),
            tuple(updated),
            tuple(removed),
            tuple(unchanged),
            tuple(conflicts),
            tuple(orphaned),
            unresolved,
        )

    def _stage(
        self,
        pack: Modpack,
        side: Side,
        targets: dict[str, _Target],
        pending: list[str],
        adopted: dict[str, Path],
        *,
        session: Session,
        max_workers: int,
        progress: ProgressCallback | None,
        cancel: CancelToken | None,
    ) -> list[str]:
        """Put new files in the staging directory and return their paths."""
        staging = self._staging_dir
        entries = {
            relative: target.entry
            for relative in pending
            if (target := targets[relative]).entry and target.entry.is_resolved
        }
        download(
            [entry.resource(staging) for entry in entries.values()],
            session=session,
            max_workers=max_workers,
            progress=progress,
            cancel=cancel,
            task="files",
        )

        writes = [item for item in pending if targets[item].override]
        files = pack.iter_override_files(side, set(writes))
        for index, (relative, file) in enumerate(files):
            if cancel is not None:
                cancel.check()
            write_atomic(staging / relative, file)
            report(progress, "overrides", index + 1, len(writes), "file")

        copies = [item for item in pending if item in adopted and item not in writes]
        for relative in copies:
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adopted[relative], staging / relative)
        return [*entries, *writes, *copies]

    def _record(
        self,
        pack: Modpack,
        targets: dict[str, _Target],
        changes: Changes,
        overwrite: bool,
        cache: _HashCache,
    ) -> None:
        """Save what this sync installed."""
        previous = self.state.files if self.state else {}
        # Kept files record the pack's hash, so they stay conflicts on the next sync.
        kept: set[str] = set() if overwrite else set(changes.conflicts)
        files: dict[str, str] = {}
        for relative, target in targets.items():
            if relative in kept:
                files[relative] = target.hashes.get("sha1") or previous.get(
                    relative, ""
                )
            else:
                files[relative] = cache.digest(relative)
        state = InstanceState(
            pack_name=pack.name,
            pack_version=pack.version,
            minecraft=pack.minecraft,
            loader_kind=pack.loader_kind,
            loader_version=pack.loader_version,
            files=files,
            kept=tuple(sorted(kept)),
            synced_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        write_json(self._state_path, asdict(state))

    def sync(
        self,
        pack: Modpack,
        *,
        side: Side = "client",
        include_optional: bool = False,
        overwrite: bool = False,
        adopt_from: Iterable[Path | str] = (),
        session: Session | None = None,
        max_workers: int = 8,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> Changes:
        """Make this directory match a pack and return what changed.

        Install and update are the same call. New files are downloaded to a
        staging directory first, so the instance is only touched once everything
        is ready. An interrupted sync can simply be run again, and it reuses what
        was already downloaded. A file whose size and modification time have not
        changed since the last sync is assumed to have the same contents.

        Args:
            pack: The modpack.
            side: The side to install.
            include_optional: Include the pack's optional files.
            overwrite: Replace the player's changes instead of keeping them.
            adopt_from: Folders to search for entries that cannot be downloaded.
                Files are found by name and verified.
            session: The session to use. A temporary one is created if omitted.
            max_workers: How many files to download at once.
            progress: Receives updates for each stage.
            cancel: Stops the sync. It has no effect once files are being moved
                into the instance.

        Returns:
            What changed.

        Raises:
            LockedError: Another sync or delete is using this instance.
            UnresolvedEntriesError: Entries are still missing. Nothing has been
                changed.
            InstanceError: The state file is corrupt, or a file could not be
                replaced, usually because the game is running. Everything is
                put back as it was.
            PackError: The pack's files are unsafe.
            DownloadError: A file could not be downloaded.
            Cancelled: ``cancel`` was triggered.
        """
        if self._backup_dir.is_dir():
            with file_lock(self._lock_path, wait=0):
                self._restore_backup()
        cache = _HashCache(self.path)
        targets, unresolved = _targets(pack, side, include_optional, cache)
        folders = [Path(folder) for folder in adopt_from]
        adopted = _find_adoptable(unresolved, folders)
        missing = [
            entry
            for entry in unresolved
            if entry.path is None
            or not (entry.path in adopted or (self.path / entry.path).is_file())
        ]
        if missing:
            raise UnresolvedEntriesError(missing)

        with file_lock(self._lock_path, wait=0):
            changes = self._classify(targets, unresolved, cache)
            pending = [*changes.added, *changes.updated]
            if overwrite:
                pending.extend(changes.conflicts)
            with session_scope(session) as client:
                staged = self._stage(
                    pack,
                    side,
                    targets,
                    pending,
                    adopted,
                    session=client,
                    max_workers=max_workers,
                    progress=progress,
                    cancel=cancel,
                )
            if cancel is not None:
                cancel.check()
            self._commit(staged, changes.removed)
            self._record(pack, targets, changes, overwrite, cache)
            cache.save()
            return changes

    def _commit(self, staged: list[str], removed: tuple[str, ...]) -> None:
        """Move staged files into place, undoing everything if a move fails."""
        backup = self._backup_dir
        staging = self._staging_dir
        placed: list[str] = []
        try:
            for relative in [*staged, *removed]:
                if (self.path / relative).is_file():
                    _move(self.path / relative, backup / relative)
            for relative in staged:
                _move(staging / relative, self.path / relative)
                placed.append(relative)
        except OSError as e:
            for relative in placed:
                _move(self.path / relative, staging / relative)
            self._restore_backup()
            raise InstanceError(
                f"Cannot update {self.path}, so it was left as it was. "
                f"Check that the game is closed: {e}"
            ) from e
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)

    def _restore_backup(self) -> None:
        """Put back files from a commit that did not finish."""
        backup = self._backup_dir
        if not backup.is_dir():
            return
        for path in [item for item in backup.rglob("*") if item.is_file()]:
            _move(path, self.path / path.relative_to(backup))
        shutil.rmtree(backup, ignore_errors=True)

    def delete(self) -> None:
        """Delete this instance's directory. Refuses unmanaged directories.

        Raises:
            InstanceError: The directory has no state from a previous sync.
            LockedError: A sync is using this instance.
        """
        if self.state is None:
            raise InstanceError(f"{self.path} is not a modsmith instance")
        with file_lock(self._lock_path, wait=0):
            # Windows cannot delete the open lock file, so that part goes last.
            for path in self.path.iterdir():
                if path.name == STATE_DIR:
                    continue
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        shutil.rmtree(self.path)
