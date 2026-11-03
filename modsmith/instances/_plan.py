"""Choosing releases to add to an instance, with their dependencies."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from ..errors import UnsupportedError
from ..packs import FileRef, PackEntry, safe_relative
from ..platforms import Platform, Project, Release, Resolution, resolve_dependencies
from ..platforms._base import PROJECT_FOLDERS, folder_kind
from ..progress import CancelToken
from ._state import Addition, Changes, InstanceState


@dataclass(frozen=True)
class Plan:
    """What `Instance.add` would install. Build one with `Instance.plan`.

    Attributes:
        additions: The additions to install, or to replace older releases of
            the same projects.
        resolution: The dependency search, with any conflicts and missing
            dependencies.
        skipped: Requested releases that the instance's pack already provides.
        unavailable: Requested projects with no release for the instance's
            game version and loader. For `Instance.plan_updates`, these are
            additions that no longer have one.
        changes: What `Instance.add` would change, as of planning.
    """

    additions: tuple[Addition, ...] = ()
    resolution: Resolution = field(default_factory=Resolution)
    skipped: tuple[Release, ...] = ()
    unavailable: tuple[str, ...] = ()
    changes: Changes = field(default_factory=Changes)

    @property
    def ok(self) -> bool:
        """Whether `Instance.add` can go ahead.

        It can if there are no conflicts and no required dependency is missing.
        """
        missing = (
            item.dependency.kind == "required" for item in self.resolution.missing
        )
        return not self.resolution.conflicts and not any(missing)


def check_type(state: InstanceState, project_type: str) -> None:
    """Refuse kinds of projects that cannot be added to this instance.

    Raises:
        UnsupportedError: The kind has no folder, or it is a mod and the
            instance has no mod loader.
    """
    if project_type not in PROJECT_FOLDERS:
        raise UnsupportedError(f"A {project_type} cannot be added to an instance")
    if project_type == "mod" and not state.loader_kind:
        raise UnsupportedError("This instance has no mod loader, so it takes no mods")


def newest(
    platform: Platform, project: Project, state: InstanceState, release_only: bool
) -> Release | None:
    """Return a project's newest release that works in this instance."""
    # Resource and shader packs list the game, or a shader loader, as their loader.
    loader = state.loader_kind if project.project_type == "mod" else None
    return platform.latest_release(
        project,
        game_version=state.minecraft,
        loader=loader,
        release_only=release_only,
    )


def to_addition(
    platform: str,
    release: Release,
    project: Project,
    *,
    requires: tuple[str, ...] = (),
    requested: bool = True,
    pinned: bool = False,
    path: str | None = None,
) -> Addition:
    """Describe a release as an addition.

    Raises:
        UnsupportedError: The project's kind has no folder in an instance.
        PlatformError: The release has no files.
        PackError: The file name is unsafe.
    """
    kind = folder_kind(project.project_type)
    if kind is None:
        raise UnsupportedError(
            f"{project.name} is a {project.project_type}, "
            "which cannot be added to an instance"
        )
    folder = PROJECT_FOLDERS[kind]
    file = release.primary_file
    entry = PackEntry(
        path=path or safe_relative(f"{folder}/{file.name}"),
        urls=file.urls,
        hashes=dict(file.hashes),
        size=file.size,
        ref=FileRef(platform, release.project_id, release.id),
        manual_url=None if file.urls else project.url,
    )
    return Addition(
        entry,
        project.name,
        project.slug,
        kind,
        requested=requested,
        requires=requires,
        pinned=pinned,
    )


def build_plan(
    platform: Platform,
    state: InstanceState,
    roots: list[Release],
    projects: dict[str, Project],
    *,
    requested: Collection[str],
    include_optional: bool,
    release_only: bool,
    unavailable: tuple[str, ...],
    cancel: CancelToken | None,
) -> Plan:
    """Resolve dependencies and describe what to add. Changes are left empty.

    Args:
        platform: The platform the releases are from.
        state: The instance's state.
        roots: The releases to install.
        projects: Projects already looked up, keyed by id.
        requested: The ids of projects the caller asked for.
        include_optional: Also install optional dependencies.
        release_only: Leave out alpha and beta releases for dependencies.
        unavailable: Requested projects that had no release.
        cancel: Stops the search.
    """
    provided = {(ref.platform, ref.project_id) for ref in state.pack_refs}
    skipped = tuple(
        release for release in roots if (platform.name, release.project_id) in provided
    )
    wanted = [release for release in roots if release not in skipped]
    root_ids = {release.project_id for release in wanted}
    installed = [
        *state.pack_refs,
        *(
            addition.entry.ref
            for addition in state.additions
            if addition.entry.ref and addition.project_id not in root_ids
        ),
    ]
    resolution = resolve_dependencies(
        platform,
        wanted,
        game_version=state.minecraft,
        loader=state.loader_kind or "",
        include_optional=include_optional,
        release_only=release_only,
        installed=installed,
        cancel=cancel,
    )

    existing = {
        addition.project_id: addition
        for addition in state.additions
        if addition.platform == platform.name
    }
    owners = {addition.release_id: addition.project_id for addition in state.additions}
    owners.update({release.id: release.project_id for release in resolution.releases})
    kinds = {"required", "optional"} if include_optional else {"required"}
    additions: list[Addition] = []
    missing = [
        item.project_id
        for item in resolution.releases
        if item.project_id not in projects
    ]
    projects = {**projects, **platform.get_projects(missing)}
    for release in resolution.releases:
        if cancel is not None:
            cancel.check()
        project = projects.get(release.project_id) or platform.get_project(
            release.project_id, project_type="mod"
        )
        needs = (
            dependency.project_id or owners.get(dependency.release_id or "")
            for dependency in release.dependencies
            if dependency.kind in kinds
        )
        old = existing.get(release.project_id)
        additions.append(
            to_addition(
                platform.name,
                release,
                project,
                requires=tuple(dict.fromkeys(item for item in needs if item)),
                requested=(old is not None and old.requested)
                or release.project_id in requested,
                pinned=old is not None and old.pinned,
            )
        )
    return Plan(tuple(additions), resolution, skipped, unavailable)


def unneeded(additions: list[Addition]) -> list[Addition]:
    """Leave out dependencies that no remaining addition needs."""
    kept = list(additions)
    while True:
        needed = {project for item in kept for project in item.requires}
        remaining = [
            item for item in kept if item.requested or item.project_id in needed
        ]
        if len(remaining) == len(kept):
            return kept
        kept = remaining


def merge(old: Iterable[Addition], new: Iterable[Addition]) -> list[Addition]:
    """Put new additions in place of older releases of the same projects."""
    merged = {(item.platform, item.project_id): item for item in old}
    merged.update({(item.platform, item.project_id): item for item in new})
    return list(merged.values())
