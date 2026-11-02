"""Search and fetch from mod platforms. Subclass `Platform` to add another."""

from ._base import (
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

__all__ = [
    "CurseForge",
    "Modrinth",
    "Platform",
    "Project",
    "ProjectType",
    "Release",
    "ReleaseFile",
    "ReleaseType",
    "SearchResults",
]
