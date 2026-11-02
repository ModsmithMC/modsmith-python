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
EXPECTED = {
    "instances": {"Changes", "Instance", "InstanceState"},
    "launcher": {"Launcher", "Profile", "icon_data_uri", "is_running"},
    "net": {"Resource", "Session", "download", "file_hash"},
    "java": {
        "JavaRuntime",
        "download",
        "find",
        "find_all",
        "official_runtime_dirs",
        "platform_key",
        "required_for",
    },
}


def test_top_level_exports_exist():
    for name in ms.__all__:
        assert hasattr(ms, name)


@pytest.mark.parametrize("name", MODULES)
def test_module_exports_exist_and_are_public(name):
    module = importlib.import_module(f"modsmith.{name}")
    assert module.__all__ == sorted(module.__all__, key=str)
    for item in module.__all__:
        assert hasattr(module, item)
        assert not item.startswith("_")


@pytest.mark.parametrize(("name", "exports"), EXPECTED.items())
def test_stable_exports(name, exports):
    assert exports <= set(importlib.import_module(f"modsmith.{name}").__all__)


def test_no_application_facade_or_global_settings():
    assert not hasattr(ms, "CurseCraft")
    assert not hasattr(ms, "Settings")
