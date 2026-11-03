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
