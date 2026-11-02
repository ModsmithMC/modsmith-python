"""Install loaders from a local Maven repository using real processors."""

import json
from pathlib import Path

import pytest

from modsmith.errors import LoaderError, ProcessorError
from modsmith.loaders import Fabric, Forge, Quilt
from modsmith.minecraft import GameDir, maven_path
from tests.lib.builders import jdk_home, link_directory, sha1, write_zip
from tests.lib.server import Reply

VERSION_ID = "1.16.5-forge-36.2.42"
BARE_JAR = "net/minecraftforge/forge/1.16.5-36.2.42/forge-1.16.5-36.2.42.jar"
UNIVERSAL_JAR = (
    "net/minecraftforge/forge/1.16.5-36.2.42/forge-1.16.5-36.2.42-universal.jar"
)
PATCH_DATA = b"patch-data"


def artifact(path, url="", sha=""):
    return {"artifact": {"path": path, "url": url, "sha1": sha, "size": 0}}


def publish_forge(server, tmp_path, processor_jars, *, minecraft="1.16.5"):
    tool, helper = processor_jars
    tool_bytes = tool.read_bytes()
    tool_url = server.add_body("/libs/tool.jar", tool_bytes)
    profile = {
        "spec": 0,
        "version": VERSION_ID,
        "minecraft": minecraft,
        "json": "/version.json",
        "libraries": [
            {
                "name": "net.minecraftforge:forge:1.16.5-36.2.42:universal",
                "downloads": artifact(UNIVERSAL_JAR),
            },
            {
                "name": "demo:tool:1",
                "downloads": artifact(
                    maven_path("demo:tool:1"), tool_url, sha1(tool_bytes)
                ),
            },
            {
                "name": "demo:helper:1",
                "downloads": artifact(maven_path("demo:helper:1")),
            },
        ],
        "processors": [
            {
                "sides": ["server"],
                "jar": "demo:tool:1",
                "args": ["--exit", "9"],
            },
            {
                "jar": "demo:tool:1",
                "classpath": ["demo:helper:1"],
                "args": [
                    "--require",
                    "{MINECRAFT_JAR}",
                    "--copy",
                    "{BINPATCH}",
                    "{PATCHED}",
                ],
                "outputs": {"{PATCHED}": "{PATCHED_SHA}"},
            },
        ],
        "data": {
            "BINPATCH": {"client": "/data/client.lzma", "server": "/data/server.lzma"},
            "PATCHED": {
                "client": "[demo:patched:1]",
                "server": "[demo:patched:1:server]",
            },
            "PATCHED_SHA": {"client": f"'{sha1(PATCH_DATA)}'", "server": "'x'"},
        },
    }
    version = {
        "id": VERSION_ID,
        "inheritsFrom": "1.16.5",
        "libraries": [
            {
                "name": "net.minecraftforge:forge:1.16.5-36.2.42",
                "downloads": artifact(BARE_JAR),
            },
            {
                "name": "demo:patched:1",
                "downloads": artifact(maven_path("demo:patched:1")),
            },
        ],
    }
    installer = write_zip(
        tmp_path / "built" / "installer.jar",
        {
            "install_profile.json": json.dumps(profile),
            "version.json": json.dumps(version),
            f"maven/{UNIVERSAL_JAR}": b"universal",
            f"maven/{BARE_JAR}": b"bare",
            f"maven/{maven_path('demo:helper:1')}": helper.read_bytes(),
            "data/client.lzma": PATCH_DATA,
        },
    ).read_bytes()
    loader = Forge(
        "36.2.42", "1.16.5", server.base, java_index_url=server.url("/java-index")
    )
    path = loader.installer_url().removeprefix(server.base)
    server.add_body(f"{path}.sha1", sha1(installer).encode())
    server.add_body(path, installer)
    server.add_json("/java-index", {})
    return loader


def publish_vanilla(server, game):
    jar_url = server.add_body("/client.jar", b"client")
    game.write_version(
        "1.16.5",
        {
            "id": "1.16.5",
            "javaVersion": {"component": "java-runtime-delta"},
            "downloads": {
                "client": {"url": jar_url, "sha1": sha1(b"client"), "size": 6}
            },
        },
    )


def link_real_runtime(game, java, component):
    link_directory(
        jdk_home(java),
        game.path / "runtime" / component / "windows-x64" / component,
    )


def broken_runtime(game, component):
    path = (
        game.path / "runtime" / component / "windows-x64" / component / "bin/java.exe"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a program")


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cache"


def test_forge_install_end_to_end(
    server, session, game, tmp_path, processor_jars, java, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    link_real_runtime(game, java, "java-runtime-delta")

    version_id = loader.install(game, cache_dir=cache, session=session)

    assert version_id == VERSION_ID
    assert game.library("demo:patched:1").read_bytes() == PATCH_DATA
    assert "/demo/patched/1/patched-1.jar" not in {r.path for r in server.requests}
    assert (game.libraries_dir / UNIVERSAL_JAR).read_bytes() == b"universal"
    assert (game.libraries_dir / BARE_JAR).read_bytes() == b"bare"
    assert game.client_jar("1.16.5").read_bytes() == b"client"
    assert game.version(VERSION_ID).inherits_from == "1.16.5"
    assert loader.is_installed(game, session=session, cache_dir=cache)
    assert server.hits("/java-index") == []


def test_relative_paths_work_in_the_processor_directory(
    server, session, game, tmp_path, processor_jars, java, monkeypatch
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    monkeypatch.chdir(tmp_path)

    relative = GameDir(game.path.name)
    version_id = loader.install(
        relative, java=java, cache_dir=Path("cache"), session=session
    )

    assert relative.library("demo:patched:1").read_bytes() == PATCH_DATA
    assert relative.has_version(version_id)


def test_is_installed_uses_no_network(server, game, cache):
    loader = Forge("36.2.42", "1.16.5", repository=server.base)
    assert not loader.is_installed(game, cache_dir=cache)
    game.write_version(VERSION_ID, {"id": VERSION_ID})
    assert loader.is_installed(game, cache_dir=cache)
    assert server.requests == []


def test_install_of_an_installed_version_uses_no_network(server, game, cache):
    loader = Forge("36.2.42", "1.16.5", repository=server.base)
    game.write_version(VERSION_ID, {"id": VERSION_ID})
    assert loader.install(game, cache_dir=cache) == VERSION_ID
    assert server.requests == []


def test_second_install_does_nothing(
    server, session, game, tmp_path, processor_jars, java, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    loader.install(game, java=java, cache_dir=cache, session=session)
    calls = len(server.requests)
    assert loader.install(game, cache_dir=cache, session=session) == VERSION_ID
    assert len(server.requests) == calls


def test_explicit_java_is_used(
    server, session, game, tmp_path, processor_jars, java, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    assert loader.install(game, java=java, cache_dir=cache, session=session)


def test_failed_patch_does_not_register_version(
    server, session, game, tmp_path, processor_jars, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    broken_runtime(game, "java-runtime-delta")
    with pytest.raises(ProcessorError):
        loader.install(game, cache_dir=cache, session=session)
    assert not game.has_version(VERSION_ID)


def test_exact_runtime_failure_does_not_download(
    server, session, game, tmp_path, processor_jars, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    broken_runtime(game, "java-runtime-delta")
    with pytest.raises(ProcessorError):
        loader.install(game, cache_dir=cache, session=session)
    assert server.hits("/java-index") == []


def test_other_official_runtime_avoids_a_download(
    server, session, game, tmp_path, processor_jars, java, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    link_real_runtime(game, java, "java-runtime-gamma")
    assert loader.install(game, cache_dir=cache, session=session) == VERSION_ID
    assert server.hits("/java-index") == []


def test_broken_fallback_runtime_triggers_a_download(
    server, session, game, tmp_path, processor_jars, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    broken_runtime(game, "java-runtime-gamma")
    with pytest.raises(ProcessorError):
        loader.install(game, cache_dir=cache, session=session)
    assert len(server.hits("/java-index")) == 1


def test_mismatched_installer_is_rejected(
    server, session, game, tmp_path, processor_jars, cache
):
    loader = publish_forge(server, tmp_path, processor_jars, minecraft="1.20.1")
    with pytest.raises(LoaderError):
        loader.install(game, cache_dir=cache, session=session)


def test_installer_without_sha1_file(
    server, session, game, tmp_path, processor_jars, java, cache
):
    loader = publish_forge(server, tmp_path, processor_jars)
    publish_vanilla(server, game)
    path = loader.installer_url().removeprefix(server.base)
    server.add(f"{path}.sha1", Reply(status=404))
    assert loader.install(game, java=java, cache_dir=cache, session=session)


@pytest.mark.parametrize("cls", [Fabric, Quilt], ids=["fabric", "quilt"])
def test_meta_loader_install(server, session, game, cls):
    publish_vanilla(server, game)
    version_id = f"{cls.kind}-loader-0.16.10-1.16.5"
    server.add_body("/maven/net/fabricmc/loader/1/loader-1.jar", b"lib")
    server.add_body("/maven/org/other/2/other-2.jar", b"other")
    server.add_json(
        "/meta/versions/loader/1.16.5/0.16.10/profile/json",
        {
            "id": version_id,
            "libraries": [
                {
                    "name": "net.fabricmc:loader:1",
                    "url": server.url("/maven/"),
                    "sha1": sha1(b"lib"),
                },
                {"name": "org:other:2", "url": server.url("/maven")},
            ],
        },
    )
    loader = cls("0.16.10", "1.16.5", server.url("/meta"))

    assert loader.install(game, session=session) == version_id
    assert game.library("net.fabricmc:loader:1").read_bytes() == b"lib"
    assert game.library("org:other:2").read_bytes() == b"other"
    assert loader.is_installed(game, session=session)
