"""Search and fetch from mod platforms. Subclass `Platform` to add another."""

from ._base import (
    Dependency,
    DependencyKind,
    Platform,
    Project,
    ProjectType,
    Release,
    ReleaseFile,
    ReleaseType,
    SearchResults,
)
from ._curseforge import CurseForge
from ._modrinth import Modrinth
from ._resolve import Conflict, MissingDependency, Resolution, resolve_dependencies

# isort: split
# Shared with other modsmith packages, but not part of the public API.
from ._base import PROJECT_FOLDERS as PROJECT_FOLDERS

__all__ = [
    "Conflict",
    "CurseForge",
    "Dependency",
    "DependencyKind",
    "MissingDependency",
    "Modrinth",
    "Platform",
    "Project",
    "ProjectType",
    "Release",
    "ReleaseFile",
    "ReleaseType",
    "Resolution",
    "SearchResults",
    "resolve_dependencies",
]
