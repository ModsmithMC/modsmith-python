"""A real `Platform` subclass that keeps its catalogue in memory."""

from collections.abc import Iterator
from typing import ClassVar

from modsmith.errors import PlatformError
from modsmith.platforms import (
    Dependency,
    DependencyKind,
    Platform,
    Project,
    Release,
    SearchResults,
)


def release(
    project: str,
    version: str = "1",
    *dependencies: Dependency,
    game: str = "1.21.1",
    loader: str = "fabric",
    release_type: str = "release",
) -> Release:
    """Build a release whose id is ``project-version``."""
    return Release(
        platform="catalog",
        id=f"{project}-{version}",
        project_id=project,
        name=f"{project} {version}",
        release_type=release_type,  # type: ignore[arg-type]
        game_versions=(game,),
        loaders=(loader,),
        dependencies=dependencies,
    )


def on(
    project: str | None, kind: DependencyKind = "required", exact: str | None = None
) -> Dependency:
    """Build a dependency."""
    return Dependency(kind, project, exact)


class Catalog(Platform):
    """A platform that serves the releases it is given, newest first."""

    name: ClassVar[str] = "catalog"

    def __init__(self, *releases: Release) -> None:
        super().__init__()
        self.releases = releases

    def search(self, query, **options) -> SearchResults:  # type: ignore[override]
        return SearchResults((), 0)

    def get_project(self, ref, *, project_type="modpack") -> Project:
        if not any(item.project_id == ref for item in self.releases):
            raise PlatformError(f"Unknown project {ref}")
        return Project(
            self.name, str(ref), str(ref), str(ref), project_type=project_type
        )

    def iter_releases(
        self, project, *, game_version=None, loader=None, release_only=False
    ) -> Iterator[Release]:
        for item in self.releases:
            if (
                item.project_id == project.id
                and (game_version is None or game_version in item.game_versions)
                and (loader is None or loader in item.loaders)
                and (not release_only or item.release_type == "release")
            ):
                yield item

    def get_release(self, release_id: str) -> Release:
        for item in self.releases:
            if item.id == release_id:
                return item
        raise PlatformError(f"Unknown release {release_id}")
