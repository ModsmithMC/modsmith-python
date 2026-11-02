import importlib

import pytest

import modsmith as ms

MODULES = [
    "errors",
    "instances",
    "java",
    "launcher",
    "loaders",
    "minecraft",
    "net",
    "packs",
    "platforms",
    "progress",
]
STABLE = {
    "instances": {"Changes", "Instance", "InstanceState"},
    "launcher": {"Launcher", "Profile", "icon_data_uri", "is_running"},
    "net": {"Resource", "Session", "download", "file_hash"},
    "java": {"JavaRuntime", "download", "find", "find_all", "required_for"},
    "loaders": {"Fabric", "Forge", "Loader", "NeoForge", "Quilt", "create", "parse"},
    "packs": {"Modpack", "PackEntry", "load"},
    "platforms": {"CurseForge", "Modrinth", "Platform", "Project", "Release"},
    "minecraft": {"GameDir", "Version", "install_version", "list_versions"},
}


def test_top_level_exports_exist():
    for name in ms.__all__:
        assert hasattr(ms, name)


@pytest.mark.parametrize("name", MODULES)
def test_module_exports_exist_and_are_public(name):
    module = importlib.import_module(f"modsmith.{name}")
    for item in module.__all__:
        assert hasattr(module, item)
        assert not item.startswith("_")


@pytest.mark.parametrize(("name", "exports"), STABLE.items())
def test_stable_exports(name, exports):
    assert exports <= set(importlib.import_module(f"modsmith.{name}").__all__)
