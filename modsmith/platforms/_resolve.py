"""Work out which releases a set of releases depends on."""

from collections.abc import Iterable
from dataclasses import dataclass

from ..errors import NetworkError, PlatformError
from ..progress import CancelToken
from ._base import Dependency, Platform, Release

# Quilt loads Fabric mods, so a Fabric release can fill a Quilt dependency.
LOADER_FALLBACKS = {"quilt": ("quilt", "fabric")}
NOT_FOUND = 404


@dataclass(frozen=True)
class Conflict:
    """Two releases that cannot be used together.

    Attributes:
        release: The release that declares the dependency.
        dependency: The dependency that cannot be met. Its kind is ``required``
            or ``optional`` if another version was already chosen, and
            ``incompatible`` if the two releases refuse each other.
        chosen: The release it clashes with.
    """

    release: Release
    dependency: Dependency
    chosen: Release


@dataclass(frozen=True)
class MissingDependency:
    """A dependency with no release for the requested game version and loader.

    Attributes:
        release: The release that declares the dependency.
        dependency: The dependency that cannot be found.
    """

    release: Release
    dependency: Dependency


@dataclass(frozen=True)
class Resolution:
    """The result of `resolve_dependencies`.

    Attributes:
        releases: What to install, each release after the ones it needs.
            Releases already installed are left out.
        conflicts: Releases that cannot be used together.
        missing: Dependencies that could not be found.
    """

    releases: tuple[Release, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    missing: tuple[MissingDependency, ...] = ()


def _is_missing(error: NetworkError) -> bool:
    """Return whether an error means the platform does not know the item."""
    return error.status == NOT_FOUND


class _Resolver:
    """The state of one `resolve_dependencies` call."""

    def __init__(
        self,
        platform: Platform,
        game_version: str,
        loader: str,
        include_optional: bool,
        release_only: bool,
        installed: dict[str, Release],
        cancel: CancelToken | None,
    ) -> None:
        self.platform = platform
        self.game_version = game_version
        self.loaders = LOADER_FALLBACKS.get(loader, (loader,))
        self.include_optional = include_optional
        self.release_only = release_only
        self.installed = installed
        self.cancel = cancel
        self.chosen: dict[str, Release] = {}
        self.visited: set[str] = set()
        self.order: list[Release] = []
        self.conflicts: list[Conflict] = []
        self.missing: list[MissingDependency] = []

    def _newest(self, project_id: str) -> Release | None:
        """Return a project's newest compatible release, if it has one."""
        project = self.platform.get_project(project_id, project_type="mod")
        for loader in self.loaders:
            releases = self.platform.iter_releases(
                project,
                game_version=self.game_version,
                loader=loader,
                release_only=self.release_only,
            )
            release = next(releases, None)
            if release is not None:
                return release
        return None

    def _find(self, dependency: Dependency) -> Release | None:
        """Fetch the release a dependency asks for, if it exists."""
        try:
            if dependency.release_id is not None:
                return self.platform.get_release(dependency.release_id)
            return self._newest(str(dependency.project_id))
        except PlatformError:
            return None
        except NetworkError as e:
            if _is_missing(e):
                return None
            raise

    def _current(self, project_id: str | None) -> Release | None:
        """Return the release already settled for a project."""
        if project_id is None:
            return None
        return self.chosen.get(project_id) or self.installed.get(project_id)

    def _follow(self, release: Release, dependency: Dependency) -> None:
        """Meet one required or optional dependency of a release."""
        current = self._current(dependency.project_id)
        if current is None:
            found = self._find(dependency)
            if found is None:
                self.missing.append(MissingDependency(release, dependency))
                return
            current = self._current(found.project_id)
            if current is None:
                self.chosen[found.project_id] = found
                current = found
        wanted = dependency.release_id
        if wanted is not None and current.id != wanted:
            self.conflicts.append(Conflict(release, dependency, current))
        elif self.chosen.get(current.project_id) is current:
            self.visit(current)

    def visit(self, release: Release) -> None:
        """Settle a release's dependencies, then put it in the install order."""
        if release.id in self.visited:
            return
        self.visited.add(release.id)
        for dependency in release.dependencies:
            if self.cancel is not None:
                self.cancel.check()
            wanted = dependency.kind == "required" or (
                dependency.kind == "optional" and self.include_optional
            )
            if wanted:
                self._follow(release, dependency)
        self.order.append(release)

    def _refused(self, dependency: Dependency) -> Release | None:
        """Return the settled release that an ``incompatible`` entry names."""
        settled = {**self.installed, **self.chosen}.values()
        for candidate in settled:
            if dependency.release_id is not None:
                if candidate.id == dependency.release_id:
                    return candidate
            elif candidate.project_id == dependency.project_id:
                return candidate
        return None

    def check_incompatible(self) -> None:
        """Record every pair of settled releases that refuse each other."""
        for release in {**self.installed, **self.chosen}.values():
            for dependency in release.dependencies:
                if dependency.kind == "incompatible":
                    other = self._refused(dependency)
                    if other is not None:
                        self.conflicts.append(Conflict(release, dependency, other))


def resolve_dependencies(
    platform: Platform,
    releases: Iterable[Release],
    *,
    game_version: str,
    loader: str,
    include_optional: bool = False,
    release_only: bool = True,
    installed: Iterable[Release] = (),
    cancel: CancelToken | None = None,
) -> Resolution:
    """Work out which releases to install so that dependencies are met.

    A dependency on an exact release uses that release, and any other uses the
    project's newest compatible release. Each project gets one release, and the
    first choice stands: a later request for another version is a conflict, not
    a new search. For the Quilt loader, Fabric releases are used when a project
    has no Quilt release.

    Problems are returned rather than raised, so a tool can show them all at once.

    Args:
        platform: The platform that the releases are from.
        releases: The releases to install. They take priority over ``installed``.
            If two belong to one project, the first is used.
        game_version: The Minecraft version.
        loader: The mod loader.
        include_optional: Also install optional dependencies.
        release_only: Leave out alpha and beta releases when choosing a version.
        installed: Releases that are already in place, such as the results of
            `Platform.identify`. They meet dependencies without being installed.
        cancel: Stops the search.

    Returns:
        What to install and what could not be met.

    Raises:
        NetworkError: The platform could not be reached.
        UnsupportedError: A dependency names a release and the platform cannot
            look up releases.
        Cancelled: ``cancel`` was triggered.
    """
    resolver = _Resolver(
        platform,
        game_version,
        loader,
        include_optional,
        release_only,
        {release.project_id: release for release in installed},
        cancel,
    )
    roots = list(releases)
    for release in roots:
        resolver.chosen.setdefault(release.project_id, release)
    for release in resolver.chosen.copy().values():
        resolver.visit(release)
    resolver.check_incompatible()
    present = {release.id for release in resolver.installed.values()}
    return Resolution(
        tuple(item for item in resolver.order if item.id not in present),
        tuple(resolver.conflicts),
        tuple(resolver.missing),
    )
