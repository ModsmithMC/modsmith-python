"""Game directories managed from a modpack.

`Instance.sync` is both install and update: it brings a directory to the state
a pack describes, tracks what it wrote, and leaves the user's changes alone.
"""

import hashlib
import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._support import write_atomic, write_json
from .errors import InstanceError, UnresolvedEntriesError
from .net import Session, download, file_hash
from .net._resource import matches
from .net._session import session_scope
from .packs import Modpack, PackEntry, Side
from .progress import CancelToken, ProgressCallback, report

__all__ = ["Changes", "Instance", "InstanceState"]

STATE_FILE = ".modsmith/instance.json"


@dataclass(frozen=True)
class InstanceState:
    """What the last sync installed. `files` maps paths to the pack's SHA-1."""

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
    """What a sync would do. Conflicts and orphans are the user's edits."""

    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    unresolved: tuple[PackEntry, ...] = ()


@dataclass(frozen=True)
class _Target:
    hashes: Mapping[str, str]
    entry: PackEntry | None = None
    data: bytes | None = None


def _targets(
    pack: Modpack, side: Side, include_optional: bool
) -> tuple[dict[str, _Target], tuple[PackEntry, ...]]:
    targets: dict[str, _Target] = {}
    unresolved: list[PackEntry] = []
    for entry in pack.entries:
        if not entry.wanted(side, include_optional):
            continue
        if not entry.is_resolved:
            unresolved.append(entry)
        if entry.path:
            targets[entry.path] = _Target(entry.hashes, entry=entry)
    for relative, data in pack.iter_overrides(side):
        targets[relative] = _Target(
            {"sha1": hashlib.sha1(data).hexdigest()}, data=data
        )
    return targets, tuple(unresolved)


class Instance:
    """A game directory whose contents come from a modpack."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @classmethod
    def open(cls, path: Path | str) -> "Instance":
        return cls(path)

    def __repr__(self) -> str:
        return f"Instance({str(self.path)!r})"

    @property
    def _state_path(self) -> Path:
        return self.path / STATE_FILE

    @property
    def state(self) -> InstanceState | None:
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
        """Compare this directory with a pack. Changes nothing."""
        targets, unresolved = _targets(pack, side, include_optional)
        return self._classify(targets, unresolved)

    def _classify(
        self, targets: dict[str, _Target], unresolved: tuple[PackEntry, ...]
    ) -> Changes:
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
            elif matches(dest, target.hashes):
                unchanged.append(relative)
            elif state is None or file_hash(dest) == managed.get(relative):
                updated.append(relative)
            else:
                conflicts.append(relative)

        removed: list[str] = []
        orphaned: list[str] = []
        for relative, expected in managed.items():
            dest = self.path / relative
            if relative in targets or not dest.is_file():
                continue
            (removed if file_hash(dest) == expected else orphaned).append(relative)
        return Changes(
            tuple(added),
            tuple(updated),
            tuple(removed),
            tuple(unchanged),
            tuple(conflicts),
            tuple(orphaned),
            unresolved,
        )

    def _adopt(self, entries: Iterable[PackEntry], folders: list[Path]) -> None:
        for entry in entries:
            if entry.path is None:
                continue
            name = Path(entry.path).name
            for folder in folders:
                candidate = folder / name
                if candidate.is_file() and matches(candidate, entry.hashes):
                    dest = self.path / entry.path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, dest)
                    break

    def _record(
        self,
        pack: Modpack,
        targets: dict[str, _Target],
        changes: Changes,
        overwrite: bool,
    ) -> None:
        previous = self.state.files if self.state else {}
        kept: set[str] = set() if overwrite else set(changes.conflicts)
        files: dict[str, str] = {}
        for relative, target in targets.items():
            if relative in kept:
                files[relative] = target.hashes.get("sha1") or previous.get(relative, "")
            else:
                files[relative] = file_hash(self.path / relative)
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

        Install and update are the same call. Files the user changed are kept
        unless `overwrite` is set. Entries that cannot be downloaded are looked
        for by name in `adopt_from`, verified, and copied in; anything still
        missing raises `UnresolvedEntriesError` before any file is written.
        An interrupted sync can simply be run again.
        """
        targets, unresolved = _targets(pack, side, include_optional)
        self._adopt(unresolved, [Path(folder) for folder in adopt_from])
        missing = [
            entry
            for entry in unresolved
            if entry.path is None or not (self.path / entry.path).is_file()
        ]
        if missing:
            raise UnresolvedEntriesError(missing)

        changes = self._classify(targets, unresolved)
        pending = [*changes.added, *changes.updated]
        if overwrite:
            pending.extend(changes.conflicts)
        downloads = [
            target.entry.resource(self.path)
            for relative in pending
            if (target := targets[relative]).entry and target.entry.is_resolved
        ]

        with session_scope(session) as client:
            download(
                downloads,
                session=client,
                max_workers=max_workers,
                progress=progress,
                cancel=cancel,
                task="files",
            )

        writes = [item for item in pending if targets[item].data is not None]
        for index, relative in enumerate(writes):
            if cancel is not None:
                cancel.check()
            data = targets[relative].data
            if data is not None:
                write_atomic(self.path / relative, data)
            report(progress, "overrides", index + 1, len(writes), "file")

        for relative in changes.removed:
            (self.path / relative).unlink(missing_ok=True)
        self._record(pack, targets, changes, overwrite)
        return changes

    def delete(self) -> None:
        """Delete this instance's directory. Refuses unmanaged directories."""
        if self.state is None:
            raise InstanceError(f"{self.path} is not a modsmith instance")
        shutil.rmtree(self.path)
