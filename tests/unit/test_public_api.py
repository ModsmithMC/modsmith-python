import importlib

import pytest

import modsmith as ms

# The complete public API. Adding or removing a name is a deliberate change:
# update this list, the reference pages and the changelog together.
PUBLIC = {
    "errors": {
        "Cancelled",
        "DependencyError",
        "DownloadError",
        "InstanceError",
        "IntegrityError",
        "JavaError",
        "LauncherError",
        "LoaderError",
        "LockedError",
        "ModsmithError",
        "NetworkError",
        "PackError",
        "PlatformError",
        "ProcessorError",
        "UnresolvedEntriesError",
        "UnsupportedError",
    },
    "instances": {
        "Addition",
        "Changes",
        "ContentFile",
        "Instance",
        "InstanceState",
        "Plan",
    },
    "java": {"JavaRuntime", "download", "find", "find_all", "required_for"},
    "launcher": {"Launcher", "Profile", "icon_data_uri", "is_running"},
    "loaders": {
        "Fabric",
        "Forge",
        "Loader",
        "LoaderVersion",
        "MetaLoader",
        "NeoForge",
        "ProcessorLoader",
        "Quilt",
        "create",
        "parse",
        "recommended",
        "register",
        "versions",
    },
    "metadata": {"Metadata", "read"},
    "minecraft": {
        "GameDir",
        "MavenCoord",
        "Version",
        "VersionInfo",
        "install_version",
        "list_versions",
        "maven_path",
    },
    "net": {"Resource", "Session", "download", "file_hash"},
    "packs": {
        "CurseForgePack",
        "FileRef",
        "Modpack",
        "Mrpack",
        "PackEntry",
        "PackFormat",
        "Side",
        "Support",
        "load",
        "register",
        "safe_relative",
    },
    "platforms": {
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
        "SearchSort",
        "resolve_dependencies",
    },
    "progress": {"CancelToken", "Progress", "ProgressCallback", "report"},
}


def test_top_level_names():
    assert set(ms.__all__) == {"CancelToken", "Progress", "__version__", *PUBLIC}
    for name in ms.__all__:
        assert hasattr(ms, name)


@pytest.mark.parametrize(("name", "exports"), PUBLIC.items())
def test_module_exports_match_the_public_list(name, exports):
    module = importlib.import_module(f"modsmith.{name}")
    assert set(module.__all__) == exports
    for item in module.__all__:
        assert hasattr(module, item)
