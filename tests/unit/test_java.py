import lzma
import sys

import pytest
import responses

from helpers import sha1
from modsmith import java
from modsmith.errors import JavaError
from modsmith.minecraft import GameDir, Version


def fake_runtime(root, component, relative="bin/java.exe", platform="windows-x64"):
    path = root / component / platform / component / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"java")
    return path


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    return GameDir(tmp_path / "mc")


def test_store_runtime_dir_is_searched(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    dirs = java.official_runtime_dirs(GameDir(tmp_path / "mc"))
    assert tmp_path / "mc" / "runtime" in dirs
    assert (
        tmp_path / "Packages" / java.STORE_PACKAGE / "LocalCache" / "Local" / "runtime"
    ) in dirs


def test_find_prefers_official_runtime(game, tmp_path):
    binary = fake_runtime(game.path / "runtime", "java-runtime-delta")
    found = java.find("java-runtime-delta", game=game, cache_dir=tmp_path)
    assert found == java.JavaRuntime("java-runtime-delta", binary)


def test_find_handles_mac_bundle(game, tmp_path):
    binary = fake_runtime(
        game.path / "runtime", "c", "jre.bundle/Contents/Home/bin/java", "mac-os-arm64"
    )
    assert java.find("c", game=game, cache_dir=tmp_path).executable == binary


def test_incomplete_cache_is_ignored(game, tmp_path):
    fake_runtime(tmp_path / "java", "java-runtime-delta")
    assert java.find("java-runtime-delta", game=game, cache_dir=tmp_path) is None
    (tmp_path / "java" / "java-runtime-delta" / java.COMPLETE_MARKER).touch()
    assert java.find("java-runtime-delta", game=game, cache_dir=tmp_path)


def test_find_all_orders_by_preference(game, tmp_path):
    gamma = fake_runtime(game.path / "runtime", "java-runtime-gamma")
    delta = fake_runtime(game.path / "runtime", "java-runtime-delta")
    found = java.find_all(game=game, cache_dir=tmp_path)
    assert [runtime.executable for runtime in found] == [delta, gamma]


def test_required_for_follows_inherits_from(tmp_path):
    game = GameDir(tmp_path)
    game.write_version("1.21", {"id": "1.21", "javaVersion": {"component": "delta"}})
    game.write_version("loader", {"id": "loader", "inheritsFrom": "1.21"})
    assert java.required_for(game.version("loader"), game) == "delta"


def test_required_for_defaults_to_legacy():
    assert java.required_for(Version("1.8")) == java.LEGACY_COMPONENT


def stub_runtime():
    binary = b"java binary"
    packed = lzma.compress(binary)
    name = "bin/java.exe" if java.platform_key().startswith("windows") else "bin/java"
    manifest = {
        "files": {
            "bin": {"type": "directory"},
            name: {
                "type": "file",
                "executable": True,
                "downloads": {
                    "raw": {"sha1": sha1(binary), "url": "https://x.test/raw"},
                    "lzma": {"sha1": sha1(packed), "url": "https://x.test/lzma"},
                },
            },
            "release": {
                "type": "file",
                "executable": False,
                "downloads": {"raw": {"sha1": sha1(b"r"), "url": "https://x.test/r"}},
            },
        }
    }
    responses.get(
        java.RUNTIME_INDEX_URL,
        json={
            java.platform_key(): {
                "java-runtime-delta": [{"manifest": {"url": "https://x.test/m"}}]
            }
        },
    )
    responses.get("https://x.test/m", json=manifest)
    responses.get("https://x.test/lzma", body=packed)
    responses.get("https://x.test/r", body=b"r")


@responses.activate
def test_download_installs_into_cache(session, game, tmp_path):
    stub_runtime()
    runtime = java.download("java-runtime-delta", cache_dir=tmp_path, session=session)
    assert runtime.executable.read_bytes() == b"java binary"
    assert runtime.executable.is_relative_to(tmp_path / "java")
    assert not runtime.executable.with_name(runtime.executable.name + ".lzma").exists()
    assert java.find("java-runtime-delta", game=game, cache_dir=tmp_path) == runtime
    assert not (game.path / "runtime").exists()


@responses.activate
def test_download_rejects_missing_platform(session, tmp_path):
    responses.get(java.RUNTIME_INDEX_URL, json={})
    with pytest.raises(JavaError):
        java.download("x", cache_dir=tmp_path, session=session)
