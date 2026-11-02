import json
import sys

import pytest
import responses

import modsmith as ms
from helpers import sha1
from modsmith.errors import UnsupportedError
from modsmith.minecraft import (
    GameDir,
    MavenCoord,
    Version,
    install_version,
    list_versions,
    maven_path,
)
from modsmith.minecraft._game_dir import default_game_path
from modsmith.minecraft._remote import VERSION_MANIFEST_URL

META_URL = "https://example.test/1.21.1.json"
JAR_URL = "https://example.test/client.jar"


def stub_version(jar=b"client"):
    meta = {
        "id": "1.21.1",
        "javaVersion": {"component": "java-runtime-delta", "majorVersion": 21},
        "downloads": {"client": {"url": JAR_URL, "sha1": sha1(jar), "size": len(jar)}},
    }
    body = json.dumps(meta).encode()
    responses.get(
        VERSION_MANIFEST_URL,
        json={
            "versions": [
                {
                    "id": "1.21.1",
                    "type": "release",
                    "url": META_URL,
                    "sha1": sha1(body),
                    "releaseTime": "2024-08-08",
                }
            ]
        },
    )
    responses.get(META_URL, body=body)


@pytest.mark.parametrize(
    ("coord", "path"),
    [
        ("net.minecraft:client:1.21", "net/minecraft/client/1.21/client-1.21.jar"),
        (
            "net.minecraftforge:forge:1.21-52:shim",
            "net/minecraftforge/forge/1.21-52/forge-1.21-52-shim.jar",
        ),
        ("de.oceanlabs:mcp:1.21:mappings@tsrg", "de/oceanlabs/mcp/1.21/mcp-1.21-mappings.tsrg"),
        ("a.b:c:1@zip", "a/b/c/1/c-1.zip"),
    ],
)
def test_maven_path(coord, path):
    assert maven_path(coord) == path


@pytest.mark.parametrize("coord", ["a:b", "a:b:c:d:e", "a:b:c@d@e"])
def test_invalid_maven_coord(coord):
    with pytest.raises(ValueError):
        MavenCoord.parse(coord)


def test_game_dir_layout(tmp_path):
    game = GameDir(tmp_path)
    assert game.version_json("1.21") == tmp_path / "versions" / "1.21" / "1.21.json"
    assert game.client_jar("1.21") == tmp_path / "versions" / "1.21" / "1.21.jar"
    assert game.library("a:b:1") == tmp_path / "libraries" / "a" / "b" / "1" / "b-1.jar"


def test_game_dir_lists_only_real_versions(tmp_path):
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


def test_windows_default_path(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert default_game_path() == tmp_path / ".minecraft"


@responses.activate
def test_list_versions(session):
    stub_version()
    versions = list_versions(session)
    assert versions[0].id == "1.21.1"
    assert versions[0].type == "release"


@responses.activate
def test_install_version_downloads_json_and_client(session, tmp_path):
    stub_version()
    responses.get(JAR_URL, body=b"client")
    game = GameDir(tmp_path)
    version = install_version(game, "1.21.1", session=session)
    assert version.java_component == "java-runtime-delta"
    assert game.client_jar("1.21.1").read_bytes() == b"client"


@responses.activate
def test_install_version_replaces_corrupt_jar_without_refetching_meta(session, tmp_path):
    responses.get(JAR_URL, body=b"client")
    game = GameDir(tmp_path)
    game.write_version(
        "1.21.1",
        {
            "id": "1.21.1",
            "downloads": {"client": {"url": JAR_URL, "sha1": sha1(b"client"), "size": 6}},
        },
    )
    game.client_jar("1.21.1").write_bytes(b"broken")
    install_version(game, "1.21.1", session=session)
    assert game.client_jar("1.21.1").read_bytes() == b"client"
    assert len(responses.calls) == 1


@responses.activate
def test_unknown_version_is_rejected(session, tmp_path):
    responses.get(VERSION_MANIFEST_URL, json={"versions": []})
    with pytest.raises(UnsupportedError):
        install_version(GameDir(tmp_path), "9.9", session=session)


def test_public_api_is_exposed():
    for name in ms.minecraft.__all__:
        assert hasattr(ms.minecraft, name)
