import sys

import pytest

from modsmith import java
from modsmith.errors import UnsupportedError
from modsmith.minecraft import GameDir, Version


def test_layout(tmp_path):
    game = GameDir(tmp_path)
    assert game.version_json("1.21") == tmp_path / "versions" / "1.21" / "1.21.json"
    assert game.client_jar("1.21") == tmp_path / "versions" / "1.21" / "1.21.jar"
    assert game.library("a:b:1") == tmp_path / "libraries" / "a" / "b" / "1" / "b-1.jar"


def test_relative_path_is_made_absolute():
    assert GameDir("minecraft").path.is_absolute()


def test_lists_only_real_versions(tmp_path):
    game = GameDir(tmp_path)
    assert game.installed_versions() == []
    game.write_version("1.21", {"id": "1.21"})
    (tmp_path / "versions" / "empty").mkdir()
    assert game.installed_versions() == ["1.21"]
    assert game.version("1.21").id == "1.21"


def test_missing_version_is_rejected(tmp_path):
    with pytest.raises(UnsupportedError):
        GameDir(tmp_path).version("1.21")


def test_version_parses_loader_json():
    version = Version.from_dict({"id": "a", "inheritsFrom": "1.21", "libraries": []})
    assert version.inherits_from == "1.21"
    assert version.java_component is None
    assert version.client_url is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows layout")
def test_windows_default_location(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert GameDir.default().path == tmp_path / ".minecraft"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS layout")
def test_macos_default_location():
    assert GameDir.default().path.name == "minecraft"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows layout")
def test_store_runtime_directory_is_searched(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    expected = (
        tmp_path / "Packages" / java.STORE_PACKAGE / "LocalCache" / "Local" / "runtime"
    )
    assert expected in java.official_runtime_dirs(GameDir(tmp_path / "mc"))


def test_required_for_follows_inherits_from(tmp_path):
    game = GameDir(tmp_path)
    game.write_version("1.21", {"id": "1.21", "javaVersion": {"component": "delta"}})
    game.write_version("loader", {"id": "loader", "inheritsFrom": "1.21"})
    assert java.required_for(game.version("loader"), game) == "delta"


def test_required_for_defaults_to_legacy():
    assert java.required_for(Version("1.8")) == java.LEGACY_COMPONENT
