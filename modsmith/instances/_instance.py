"""Game directories managed from a modpack and from projects added on their own."""

import dataclasses
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .._fs import replace_file
from .._locks import file_lock
from ..errors import DependencyError, InstanceError
from ..loaders._base import loader_name
from ..net import Session
from ..packs import Modpack, Side, safe_relative
from ..platforms import Platform, Project, ProjectType, Release
from ..platforms._base import PROJECT_FOLDERS
from ..progress import CancelToken, ProgressCallback
from ._apply import Applier, entry_targets, sync_targets
from ._plan import Plan, build_plan, check_type, merge, newest, to_addition, unneeded
from ._state import (
    DISABLED_SUFFIX,
    LOCK_FILE,
    STATE_DIR,
    STATE_FILE,
    Addition,
    Changes,
    ContentFile,
    HashCache,
    InstanceState,
    read_state,
    write_state,
)


def _now() -> str:
    """Return the current time in ISO 8601 format."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _remaining(
    state: InstanceState, projects: tuple[str, ...], keep_dependencies: bool
) -> list[Addition]:
    """Return the additions left after removing some projects.

    Raises:
        InstanceError: A name is not an addition.
    """
    unknown = [
        name
        for name in projects
        if not any(item.matches(name) for item in state.additions)
    ]
    if unknown:
        raise InstanceError(f"Not added on its own: {', '.join(unknown)}")
    remaining = [
        item
        for item in state.additions
        if not any(item.matches(name) for name in projects)
    ]
    return remaining if keep_dependencies else unneeded(remaining)


class Instance:
    """A game directory whose contents come from a modpack and added projects.

    Args:
        path: The directory. It is created by the first sync, or by `create`.

    Attributes:
        path: The directory.
    """

    def __init__(self, path: Path | str) -> None:
        self.path: Path = Path(path)

    @classmethod
    def create(
        cls,
        path: Path | str,
        *,
        minecraft: str,
        loader: str | None = None,
        loader_version: str | None = None,
    ) -> "Instance":
        """Start an instance that does not come from a pack.

        Only the versions are recorded. Install the game and the loader with
        ``modsmith.minecraft`` and ``modsmith.loaders``, then add projects with
        `plan` and `add`.

        Args:
            path: The directory.
            minecraft: The Minecraft version.
            loader: The mod loader's name, or None for vanilla.
            loader_version: The mod loader's version.

        Returns:
            The instance.

        Raises:
            InstanceError: The directory is already an instance.
            LockedError: Another process is creating it.
        """
        instance = cls(path)
        with file_lock(instance._lock_path, wait=0):
            if instance.state is not None:
                raise InstanceError(f"{instance.path} is already an instance")
            state = InstanceState(
                minecraft=minecraft,
                loader_kind=loader_name(loader) if loader else None,
                loader_version=loader_version,
                synced_at=_now(),
            )
            write_state(instance._state_path, state)
        return instance

    def __repr__(self) -> str:
        return f"Instance({str(self.path)!r})"

    @property
    def _state_path(self) -> Path:
        """The file that records the instance's contents."""
        return self.path / STATE_FILE

    @property
    def _lock_path(self) -> Path:
        """The file that keeps two changes out of this directory."""
        return self.path / LOCK_FILE

    @property
    def _files(self) -> Applier:
        """The transaction engine for this directory."""
        return Applier(self.path)

    @property
    def state(self) -> InstanceState | None:
        """What the instance holds, or None if it is not an instance yet.

        Raises:
            InstanceError: The state file is corrupt.
        """
        return read_state(self._state_path)

    def _require_state(self) -> InstanceState:
        """Return the state, or explain that this is not an instance yet."""
        state = self.state
        if state is None:
            raise InstanceError(
                f"{self.path} is not an instance. Sync a pack or call "
                "Instance.create first."
            )
        return state

    @property
    def additions(self) -> tuple[Addition, ...]:
        """The projects installed on their own. Empty if this is not an instance.

        Raises:
            InstanceError: The state file is corrupt.
        """
        state = self.state
        return state.additions if state else ()

    def contents(self) -> tuple[ContentFile, ...]:
        """List the mods, resource packs and shader packs in the instance.

        Returns:
            Each one, with where it came from and whether it is enabled. Use
            `modsmith.metadata.read` for its name and version.

        Raises:
            InstanceError: The state file is corrupt.
        """
        state = self.state
        pack_files = set(state.files) if state else set[str]()
        additions = {item.path: item for item in state.additions} if state else {}
        found: list[ContentFile] = []
        for folder in sorted(set(PROJECT_FOLDERS.values())):
            directory = self.path / folder
            if not directory.is_dir():
                continue
            for item in sorted(directory.iterdir()):
                # Mod loaders do not load folders inside the mods folder.
                if not (item.is_file() or (item.is_dir() and folder != "mods")):
                    continue
                relative = f"{folder}/{item.name}"
                path = relative.removesuffix(DISABLED_SUFFIX)
                addition = additions.get(path)
                source = (
                    "addition" if addition else "pack" if path in pack_files else "user"
                )
                found.append(ContentFile(path, path == relative, source, addition))
        return tuple(found)

    @staticmethod
    def _managed(state: InstanceState | None) -> dict[str, str]:
        """Return the hash recorded for every file the instance manages."""
        if state is None:
            return {}
        managed = dict(state.files)
        managed.update({item.path: item.sha1 for item in state.additions})
        return managed

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
        state = self.state
        cache = HashCache(self.path)
        wanted = sync_targets(
            pack, side, include_optional, cache, state.additions if state else ()
        )
        changes, _ = self._files.classify(
            wanted.all,
            tuple(wanted.unresolved),
            cache,
            self._managed(state),
            state is None,
        )
        return dataclasses.replace(
            changes, superseded=tuple(item.path for item in wanted.superseded)
        )

    def _recover(self) -> None:
        """Finish undoing a commit that was interrupted."""
        if self._files.backup.is_dir():
            with file_lock(self._lock_path, wait=0):
                self._files.restore_backup()

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

        Additions stay, unless the pack now provides the same project or file.
        Disabled files stay disabled, and are updated under their disabled name.

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
            LockedError: Another change is using this instance.
            UnresolvedEntriesError: Entries are still missing. Nothing has been
                changed.
            InstanceError: The state file is corrupt, or a file could not be
                replaced, usually because the game is running. Everything is
                put back as it was.
            PackError: The pack's files are unsafe.
            DownloadError: A file could not be downloaded.
            Cancelled: ``cancel`` was triggered.
        """
        self._recover()
        state = self.state
        cache = HashCache(self.path)
        wanted = sync_targets(
            pack, side, include_optional, cache, state.additions if state else ()
        )
        adopted = self._files.check_unresolved(wanted.unresolved, adopt_from)

        with file_lock(self._lock_path, wait=0):
            state = self.state
            applied = self._files.apply(
                wanted.all,
                wanted.unresolved,
                self._managed(state),
                fresh=state is None,
                pack=pack,
                side=side,
                overwrite=overwrite,
                adopted=adopted,
                cache=cache,
                session=session,
                max_workers=max_workers,
                progress=progress,
                cancel=cancel,
            )
            refs = (target.entry.ref for target in wanted.pack.values() if target.entry)
            write_state(
                self._state_path,
                InstanceState(
                    minecraft=pack.minecraft,
                    loader_kind=loader_name(pack.loader_kind)
                    if pack.loader_kind
                    else None,
                    loader_version=pack.loader_version,
                    pack_name=pack.name,
                    pack_version=pack.version,
                    files={item: applied.hashes[item] for item in wanted.pack},
                    kept=tuple(sorted(applied.kept)),
                    additions=tuple(
                        dataclasses.replace(item, sha1=applied.hashes[item.path])
                        for item in wanted.staying
                    ),
                    pack_refs=tuple(ref for ref in refs if ref),
                    synced_at=_now(),
                ),
            )
            cache.save()
            return dataclasses.replace(
                applied.changes,
                superseded=tuple(item.path for item in wanted.superseded),
            )

    def _replace_additions(
        self,
        state: InstanceState,
        additions: list[Addition],
        *,
        overwrite: bool,
        adopt_from: Iterable[Path | str],
        session: Session | None,
        max_workers: int,
        progress: ProgressCallback | None,
        cancel: CancelToken | None,
    ) -> Changes:
        """Make the instance hold exactly these additions. Hold the lock."""
        cache = HashCache(self.path)
        targets, unresolved = entry_targets(item.entry for item in additions)
        adopted = self._files.check_unresolved(unresolved, adopt_from)
        managed = {item.path: item.sha1 for item in state.additions}
        applied = self._files.apply(
            targets,
            unresolved,
            managed,
            fresh=False,
            pack=None,
            side="client",
            overwrite=overwrite,
            adopted=adopted,
            cache=cache,
            session=session,
            max_workers=max_workers,
            progress=progress,
            cancel=cancel,
        )
        kept = (set(state.kept) - set(managed)) | applied.kept
        write_state(
            self._state_path,
            dataclasses.replace(
                state,
                kept=tuple(sorted(kept)),
                additions=tuple(
                    dataclasses.replace(item, sha1=applied.hashes[item.path])
                    for item in additions
                ),
                synced_at=_now(),
            ),
        )
        cache.save()
        return applied.changes

    def _preview(self, state: InstanceState, additions: list[Addition]) -> Changes:
        """Return what holding exactly these additions would change."""
        targets, unresolved = entry_targets(item.entry for item in additions)
        managed = {item.path: item.sha1 for item in state.additions}
        changes, _ = self._files.classify(
            targets, tuple(unresolved), HashCache(self.path), managed, False
        )
        return changes

    def plan(
        self,
        platform: Platform,
        items: Iterable[str | Project | Release],
        *,
        project_type: ProjectType = "mod",
        include_optional: bool = False,
        release_only: bool = True,
        cancel: CancelToken | None = None,
    ) -> Plan:
        """Work out what adding projects would install. Changes nothing.

        For a project, its newest release for the instance's game version and
        loader is chosen. A release is used as given. Dependencies are found
        with `modsmith.platforms.resolve_dependencies`, and anything the pack or
        an earlier addition already provides counts as installed.

        Args:
            platform: The platform to install from.
            items: Project ids, slugs or URLs, projects, or exact releases.
            project_type: The kind of project the items are.
            include_optional: Also install optional dependencies.
            release_only: Leave out alpha and beta releases.
            cancel: Stops the search.

        Returns:
            The plan. Pass it to `add`.

        Raises:
            InstanceError: This is not an instance yet.
            UnsupportedError: That kind of project cannot be added, or the
                instance has no mod loader for a mod.
            NetworkError: The platform could not be reached.
            Cancelled: ``cancel`` was triggered.
        """
        state = self._require_state()
        check_type(state, project_type)
        roots: list[Release] = []
        projects: dict[str, Project] = {}
        unavailable: list[str] = []
        for item in items:
            if isinstance(item, Release):
                roots.append(item)
                continue
            project = (
                item
                if isinstance(item, Project)
                else platform.get_project(item, project_type=project_type)
            )
            projects[project.id] = project
            release = newest(platform, project, state, release_only)
            if release is None:
                unavailable.append(project.slug or project.id)
            else:
                roots.append(release)
        plan = build_plan(
            platform,
            state,
            roots,
            projects,
            requested={release.project_id for release in roots},
            include_optional=include_optional,
            release_only=release_only,
            unavailable=tuple(unavailable),
            cancel=cancel,
        )
        merged = merge(state.additions, plan.additions)
        return dataclasses.replace(plan, changes=self._preview(state, merged))

    def plan_updates(
        self,
        platform: Platform,
        *,
        release_only: bool = True,
        cancel: CancelToken | None = None,
    ) -> Plan:
        """Work out which additions from a platform have newer releases.

        Pinned additions are left alone. Pass the plan to `add` to update.

        Args:
            platform: The platform the additions came from.
            release_only: Leave out alpha and beta releases.
            cancel: Stops the search.

        Returns:
            The plan. Additions with no release for the instance's game version
            and loader are listed in ``unavailable``.

        Raises:
            InstanceError: This is not an instance yet.
            NetworkError: The platform could not be reached.
            Cancelled: ``cancel`` was triggered.
        """
        state = self._require_state()
        roots: list[Release] = []
        projects: dict[str, Project] = {}
        unavailable: list[str] = []
        candidates = [
            item
            for item in state.additions
            if item.platform == platform.name and not item.pinned
        ]
        looked_up = platform.get_projects(item.project_id for item in candidates)
        for addition in candidates:
            if cancel is not None:
                cancel.check()
            project = looked_up.get(addition.project_id)
            if project is None:
                unavailable.append(addition.slug or addition.project_id)
                continue
            projects[project.id] = project
            release = newest(platform, project, state, release_only)
            if release is None:
                unavailable.append(addition.slug or addition.project_id)
            elif release.id != addition.release_id:
                roots.append(release)
        plan = build_plan(
            platform,
            state,
            roots,
            projects,
            requested=(),
            include_optional=False,
            release_only=release_only,
            unavailable=tuple(unavailable),
            cancel=cancel,
        )
        merged = merge(state.additions, plan.additions)
        return dataclasses.replace(plan, changes=self._preview(state, merged))

    def add(
        self,
        plan: Plan,
        *,
        overwrite: bool = False,
        adopt_from: Iterable[Path | str] = (),
        session: Session | None = None,
        max_workers: int = 8,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> Changes:
        """Install a plan's additions, replacing older releases of the same projects.

        Files are staged and committed the same way as in `sync`, so a failed
        add leaves the instance as it was.

        Args:
            plan: The plan, from `plan` or `plan_updates`.
            overwrite: Replace files the player changed instead of keeping them.
            adopt_from: Folders to search for files that cannot be downloaded,
                such as CurseForge files whose authors block other tools.
            session: The session to use. A temporary one is created if omitted.
            max_workers: How many files to download at once.
            progress: Receives updates for each stage.
            cancel: Stops the download. It has no effect once files are being
                moved into the instance.

        Returns:
            What changed.

        Raises:
            DependencyError: The plan has conflicts or missing required
                dependencies. Nothing has been changed.
            InstanceError: This is not an instance, or a file could not be
                replaced. Everything is put back as it was.
            LockedError: Another change is using this instance.
            UnresolvedEntriesError: A file has no download and was not found.
            DownloadError: A file could not be downloaded.
            Cancelled: ``cancel`` was triggered.
        """
        if not plan.ok:
            raise DependencyError(plan)
        self._require_state()
        self._recover()
        with file_lock(self._lock_path, wait=0):
            state = self._require_state()
            return self._replace_additions(
                state,
                merge(state.additions, plan.additions),
                overwrite=overwrite,
                adopt_from=adopt_from,
                session=session,
                max_workers=max_workers,
                progress=progress,
                cancel=cancel,
            )

    def remove(
        self, *projects: str, keep_dependencies: bool = False, dry_run: bool = False
    ) -> Changes:
        """Remove additions, and the dependencies nothing else needs.

        A file the player changed is kept, and listed in ``orphaned``.

        Args:
            *projects: Project ids, slugs or paths of additions.
            keep_dependencies: Keep dependencies even if nothing needs them.
            dry_run: Only work out what would change, and change nothing.

        Returns:
            What changed, or with ``dry_run``, what would change.

        Raises:
            InstanceError: A name is not an addition, for example because the
                pack installed it, or a file could not be removed.
            LockedError: Another change is using this instance.
        """
        if dry_run:
            state = self._require_state()
            remaining = _remaining(state, projects, keep_dependencies)
            return self._preview(state, remaining)
        self._require_state()
        self._recover()
        with file_lock(self._lock_path, wait=0):
            state = self._require_state()
            return self._replace_additions(
                state,
                _remaining(state, projects, keep_dependencies),
                overwrite=False,
                adopt_from=(),
                session=None,
                max_workers=1,
                progress=None,
                cancel=None,
            )

    def pin(self, project: str, pinned: bool = True) -> Addition:
        """Keep an addition at its current release, or let it update again.

        Args:
            project: The addition's project id, slug or path.
            pinned: True to pin, False to unpin.

        Returns:
            The changed addition.

        Raises:
            InstanceError: The name is not an addition.
            LockedError: Another change is using this instance.
        """
        self._require_state()
        with file_lock(self._lock_path, wait=0):
            state = self._require_state()
            for index, item in enumerate(state.additions):
                if item.matches(project):
                    changed = dataclasses.replace(item, pinned=pinned)
                    additions = list(state.additions)
                    additions[index] = changed
                    write_state(
                        self._state_path,
                        dataclasses.replace(state, additions=tuple(additions)),
                    )
                    return changed
        raise InstanceError(f"Not added on its own: {project}")

    def adopt(
        self,
        platform: Platform,
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> tuple[Addition, ...]:
        """Take over files the player put in the instance, if a platform knows them.

        Untracked files in ``mods``, ``resourcepacks`` and ``shaderpacks`` are
        identified by their contents. Those the platform knows become
        additions, so they can be updated and removed. No file is changed.

        Args:
            platform: The platform to ask.
            progress: Receives an update as each file is read.
            cancel: Stops reading files.

        Returns:
            The new additions.

        Raises:
            InstanceError: This is not an instance yet.
            LockedError: Another change is using this instance.
            NetworkError: The platform could not be reached.
            Cancelled: ``cancel`` was triggered.
        """
        self._require_state()
        with file_lock(self._lock_path, wait=0):
            state = self._require_state()
            kinds: dict[str, ProjectType] = {
                folder: kind for kind, folder in PROJECT_FOLDERS.items()
            }
            candidates = {
                self.path / item.location: item
                for item in self.contents()
                if item.source == "user" and (self.path / item.location).is_file()
            }
            found = platform.identify(candidates, progress=progress, cancel=cancel)
            looked_up = platform.get_projects(
                release.project_id for release in found.values()
            )
            taken = {(item.platform, item.project_id) for item in state.additions}
            taken |= {(ref.platform, ref.project_id) for ref in state.pack_refs}
            cache = HashCache(self.path)
            new: list[Addition] = []
            for path, release in found.items():
                if (platform.name, release.project_id) in taken:
                    continue
                taken.add((platform.name, release.project_id))
                item = candidates[path]
                kind = kinds[item.path.split("/", 1)[0]]
                project = looked_up.get(release.project_id) or platform.get_project(
                    release.project_id, project_type=kind
                )
                needs = (
                    dependency.project_id
                    for dependency in release.dependencies
                    if dependency.kind == "required" and dependency.project_id
                )
                addition = to_addition(
                    platform.name,
                    release,
                    dataclasses.replace(project, project_type=kind),
                    requires=tuple(dict.fromkeys(item for item in needs if item)),
                    path=item.path,
                )
                file = next(
                    (file for file in release.files if file.name == path.name),
                    release.primary_file,
                )
                entry = dataclasses.replace(
                    addition.entry,
                    urls=file.urls,
                    hashes=dict(file.hashes),
                    size=file.size,
                )
                sha1 = cache.digest(item.location)
                new.append(dataclasses.replace(addition, entry=entry, sha1=sha1))
            if new:
                write_state(
                    self._state_path,
                    dataclasses.replace(state, additions=(*state.additions, *new)),
                )
            cache.save()
            return tuple(new)

    def enable(self, *paths: str) -> None:
        """Switch files back on by removing their ``.disabled`` suffix.

        Args:
            *paths: Paths relative to the instance, with or without the suffix.

        Raises:
            InstanceError: A file is missing, or both names exist.
            LockedError: Another change is using this instance.
        """
        self._toggle(paths, enabled=True)

    def disable(self, *paths: str) -> None:
        """Switch files off by adding the ``.disabled`` suffix, so the game skips them.

        Syncs and updates keep them disabled.

        Args:
            *paths: Paths relative to the instance, such as ``mods/sodium.jar``.

        Raises:
            InstanceError: A file is missing, or both names exist.
            LockedError: Another change is using this instance.
        """
        self._toggle(paths, enabled=False)

    def _toggle(self, paths: Iterable[str], *, enabled: bool) -> None:
        """Add or remove the ``.disabled`` suffix."""
        self._require_state()
        with file_lock(self._lock_path, wait=0):
            for path in paths:
                relative = safe_relative(path).removesuffix(DISABLED_SUFFIX)
                on = self.path / relative
                off = self.path / (relative + DISABLED_SUFFIX)
                source, dest = (off, on) if enabled else (on, off)
                if dest.exists() and not source.exists():
                    continue
                if not source.exists():
                    raise InstanceError(f"{relative} is not in {self.path}")
                if dest.exists():
                    raise InstanceError(f"Both {on.name} and {off.name} exist")
                replace_file(source, dest)

    def delete(self) -> None:
        """Delete this instance's directory. Refuses unmanaged directories.

        Raises:
            InstanceError: The directory is not an instance.
            LockedError: A change is using this instance.
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
