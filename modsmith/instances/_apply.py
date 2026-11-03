"""Bring an instance's files to a wanted state in one transaction.

New files are staged first, then swapped in together, and a failed swap is
undone, so an instance is never left half updated.
"""

import dataclasses
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .._fs import replace_file, write_atomic
from ..errors import InstanceError, UnresolvedEntriesError
from ..net import Session, download
from ..net._resource import matches, stream_hash
from ..net._session import session_scope
from ..packs import Modpack, PackEntry, Side
from ..progress import CancelToken, ProgressCallback, report
from ._state import (
    BACKUP_DIR,
    DISABLED_SUFFIX,
    STAGING_DIR,
    Addition,
    Changes,
    HashCache,
)


@dataclass(frozen=True)
class Target:
    """What one path should contain after a change."""

    hashes: Mapping[str, str]
    entry: PackEntry | None = None
    override: bool = False


@dataclass(frozen=True)
class Applied:
    """The result of applying targets to an instance."""

    changes: Changes
    hashes: dict[str, str]
    kept: set[str]


@dataclass(frozen=True)
class SyncTargets:
    """What a sync wants on disk.

    Attributes:
        pack: The pack's targets.
        all: Every target, including additions that stay.
        unresolved: The entries with no download.
        staying: The additions that stay.
        superseded: The additions the pack now provides.
    """

    pack: dict[str, Target]
    all: dict[str, Target]
    unresolved: list[PackEntry]
    staying: list[Addition]
    superseded: list[Addition]


def entry_targets(
    entries: Iterable[PackEntry],
) -> tuple[dict[str, Target], list[PackEntry]]:
    """Return what entries want on disk, and those with no download."""
    targets: dict[str, Target] = {}
    unresolved: list[PackEntry] = []
    for entry in entries:
        if not entry.is_resolved:
            unresolved.append(entry)
        if entry.path:
            targets[entry.path] = Target(entry.hashes, entry=entry)
    return targets, unresolved


def override_targets(pack: Modpack, side: Side, cache: HashCache) -> dict[str, Target]:
    """Return what a pack's override files want on disk."""
    members = pack.override_members(side)
    unknown = {
        relative: info
        for relative, info in members.items()
        if cache.override_sha1(relative, info) is None
    }
    for relative, file in pack.iter_override_files(side, unknown):
        cache.remember_override(relative, unknown[relative], stream_hash(file))
    return {
        relative: Target(
            {"sha1": cache.override_sha1(relative, info) or ""}, override=True
        )
        for relative, info in members.items()
    }


def provided_by(pack_targets: Mapping[str, Target]) -> set[tuple[str, str]]:
    """Return the platform projects that a pack's entries come from."""
    return {
        (target.entry.ref.platform, target.entry.ref.project_id)
        for target in pack_targets.values()
        if target.entry and target.entry.ref
    }


def find_adoptable(
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


def move(source: Path, dest: Path) -> None:
    """Move a file, creating the destination's parent directories."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    replace_file(source, dest)


def sync_targets(
    pack: Modpack,
    side: Side,
    include_optional: bool,
    cache: HashCache,
    additions: Iterable[Addition],
) -> SyncTargets:
    """Work out what a sync wants on disk."""
    wanted = (entry for entry in pack.entries if entry.wanted(side, include_optional))
    pack_targets, unresolved = entry_targets(wanted)
    pack_targets.update(override_targets(pack, side, cache))
    provided = provided_by(pack_targets)
    staying: list[Addition] = []
    superseded: list[Addition] = []
    for addition in additions:
        taken = (addition.platform, addition.project_id) in provided
        if taken or addition.path in pack_targets:
            superseded.append(addition)
        else:
            staying.append(addition)
    targets, unresolved_additions = entry_targets(item.entry for item in staying)
    targets.update(pack_targets)
    unresolved.extend(unresolved_additions)
    return SyncTargets(pack_targets, targets, unresolved, staying, superseded)


class Applier:
    """Applies wanted states to one instance directory.

    Args:
        path: The instance directory.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.staging = path / STAGING_DIR
        self.backup = path / BACKUP_DIR

    def locate(self, relative: str) -> str:
        """Return where a file is on disk, which may be its disabled name."""
        if (self.path / relative).exists():
            return relative
        disabled = relative + DISABLED_SUFFIX
        return disabled if (self.path / disabled).exists() else relative

    def classify(
        self,
        targets: dict[str, Target],
        unresolved: tuple[PackEntry, ...],
        cache: HashCache,
        managed: Mapping[str, str],
        fresh: bool,
    ) -> tuple[Changes, dict[str, str]]:
        """Sort each target and managed file into `Changes`.

        Returns:
            The changes, and where each path is on disk.
        """
        located = {relative: self.locate(relative) for relative in [*targets, *managed]}
        added: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        conflicts: list[str] = []
        for relative, target in targets.items():
            actual = located[relative]
            if not (self.path / actual).is_file():
                added.append(relative)
            elif cache.matches(actual, target.hashes):
                unchanged.append(relative)
            # With no state, or a file as we left it, the player did not edit it.
            elif fresh or cache.digest(actual) == managed.get(relative):
                updated.append(relative)
            else:
                conflicts.append(relative)

        removed: list[str] = []
        orphaned: list[str] = []
        for relative, expected in managed.items():
            actual = located[relative]
            if relative in targets or not (self.path / actual).is_file():
                continue
            unedited = cache.digest(actual) == expected
            (removed if unedited else orphaned).append(relative)
        changes = Changes(
            tuple(added),
            tuple(updated),
            tuple(removed),
            tuple(unchanged),
            tuple(conflicts),
            tuple(orphaned),
            unresolved,
        )
        return changes, located

    def check_unresolved(
        self, unresolved: list[PackEntry], adopt_from: Iterable[Path | str]
    ) -> dict[str, Path]:
        """Find files for entries with no download, and fail if any is missing.

        Returns:
            The files found in ``adopt_from``, keyed by path.

        Raises:
            UnresolvedEntriesError: An entry has no download and no file.
        """
        adopted = find_adoptable(unresolved, [Path(folder) for folder in adopt_from])
        missing = [
            entry
            for entry in unresolved
            if entry.path is None
            or not (
                entry.path in adopted or (self.path / self.locate(entry.path)).is_file()
            )
        ]
        if missing:
            raise UnresolvedEntriesError(missing)
        return adopted

    def stage(
        self,
        pack: Modpack | None,
        side: Side,
        targets: dict[str, Target],
        pending: list[str],
        adopted: dict[str, Path],
        located: dict[str, str],
        *,
        session: Session,
        max_workers: int,
        progress: ProgressCallback | None,
        cancel: CancelToken | None,
    ) -> list[str]:
        """Put new files in the staging directory and return where they go."""
        staging = self.staging
        entries = {
            relative: dataclasses.replace(target.entry, path=located[relative])
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
        if pack is not None and writes:
            files = pack.iter_override_files(side, set(writes))
            for index, (relative, file) in enumerate(files):
                if cancel is not None:
                    cancel.check()
                write_atomic(staging / located[relative], file)
                report(progress, "overrides", index + 1, len(writes), "file")

        copies = [item for item in pending if item in adopted and item not in writes]
        for relative in copies:
            dest = staging / located[relative]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(adopted[relative], dest)
        return [located[relative] for relative in [*entries, *writes, *copies]]

    def apply(
        self,
        targets: dict[str, Target],
        unresolved: list[PackEntry],
        managed: Mapping[str, str],
        *,
        fresh: bool,
        pack: Modpack | None,
        side: Side,
        overwrite: bool,
        adopted: dict[str, Path],
        cache: HashCache,
        session: Session | None,
        max_workers: int,
        progress: ProgressCallback | None,
        cancel: CancelToken | None,
    ) -> Applied:
        """Bring the files in ``targets`` and ``managed`` up to date.

        Call it while holding the instance's lock.
        """
        changes, located = self.classify(
            targets, tuple(unresolved), cache, managed, fresh
        )
        pending = [*changes.added, *changes.updated]
        if overwrite:
            pending.extend(changes.conflicts)
        with session_scope(session) as client:
            staged = self.stage(
                pack,
                side,
                targets,
                pending,
                adopted,
                located,
                session=client,
                max_workers=max_workers,
                progress=progress,
                cancel=cancel,
            )
        if cancel is not None:
            cancel.check()
        self.commit(staged, [located[relative] for relative in changes.removed])

        # Kept files record the wanted hash, so they stay conflicts next time.
        kept: set[str] = set() if overwrite else set(changes.conflicts)
        hashes: dict[str, str] = {}
        for relative, target in targets.items():
            if relative in kept:
                hashes[relative] = target.hashes.get("sha1") or managed.get(
                    relative, ""
                )
            else:
                hashes[relative] = cache.digest(located[relative])
        return Applied(changes, hashes, kept)

    def commit(self, staged: list[str], removed: list[str]) -> None:
        """Move staged files into place, undoing everything if a move fails."""
        backup = self.backup
        staging = self.staging
        placed: list[str] = []
        try:
            for relative in [*staged, *removed]:
                if (self.path / relative).is_file():
                    move(self.path / relative, backup / relative)
            for relative in staged:
                move(staging / relative, self.path / relative)
                placed.append(relative)
        except OSError as e:
            for relative in placed:
                move(self.path / relative, staging / relative)
            self.restore_backup()
            raise InstanceError(
                f"Cannot update {self.path}, so it was left as it was. "
                f"Check that the game is closed: {e}"
            ) from e
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)

    def restore_backup(self) -> None:
        """Put back files from a commit that did not finish."""
        backup = self.backup
        if not backup.is_dir():
            return
        for path in [item for item in backup.rglob("*") if item.is_file()]:
            move(path, self.path / path.relative_to(backup))
        shutil.rmtree(backup, ignore_errors=True)
