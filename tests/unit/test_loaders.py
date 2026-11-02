import json
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest
import responses

import modsmith as ms
from helpers import PROFILE_FIXTURES, fake_runtime, sha1, write_jar, write_zip
from modsmith.errors import Cancelled, LoaderError, ProcessorError, UnsupportedError
from modsmith.loaders import (
    Fabric,
    Forge,
    InstallerJar,
    InstallProfile,
    Loader,
    NeoForge,
    Processor,
    Quilt,
    create,
    parse,
    register,
)
from modsmith.loaders import _processors as processors_module
from modsmith.loaders._install_profile import Variables, replace_tokens
from modsmith.loaders._processors import run_processors
from modsmith.minecraft import GameDir, maven_path

FORGE_MAVEN = "https://forge.test"


@pytest.mark.parametrize(
    ("loader_id", "minecraft", "expected"),
    [
        ("forge-47.3.0", "1.20.1", Forge("47.3.0", "1.20.1")),
        ("neoforge-21.1.233", "1.21.1", NeoForge("21.1.233", "1.21.1")),
        ("neoforge-1.20.1-47.1.106", "1.20.1", NeoForge("47.1.106", "1.20.1")),
        ("fabric-0.16.10", "1.21.1", Fabric("0.16.10", "1.21.1")),
        ("quilt-0.26.0", "1.21.1", Quilt("0.26.0", "1.21.1")),
    ],
)
def test_parse_loader_id(loader_id, minecraft, expected):
    assert parse(loader_id, minecraft) == expected


def test_create_accepts_modrinth_names():
    assert create("fabric-loader", "1", "1.21") == Fabric("1", "1.21")
    assert create("quilt-loader", "1", "1.21") == Quilt("1", "1.21")


@pytest.mark.parametrize("loader_id", ["forge", "liteloader-1"])
def test_parse_rejects_unsupported(loader_id):
    with pytest.raises(UnsupportedError):
        parse(loader_id, "1.20.1")


def test_third_party_loader_can_register():
    @register
    @dataclass(frozen=True)
    class Custom(Loader):
        kind: ClassVar[str] = "custom"

        def version_id(self, *, session=None, cache_dir=None):
            return "custom-1"

        def install(self, game, **kwargs):
            return "custom-1"

    assert isinstance(create("custom", "1", "1.21"), Custom)


@pytest.mark.parametrize(
    ("loader", "url"),
    [
        (
            Forge("47.3.0", "1.20.1", FORGE_MAVEN),
            "https://forge.test/net/minecraftforge/forge/1.20.1-47.3.0/forge-1.20.1-47.3.0-installer.jar",
        ),
        (
            NeoForge("21.1.233", "1.21.1", "https://neo.test/releases"),
            "https://neo.test/releases/net/neoforged/neoforge/21.1.233/neoforge-21.1.233-installer.jar",
        ),
        (
            NeoForge("47.1.106", "1.20.1", "https://neo.test/releases"),
            "https://neo.test/releases/net/neoforged/forge/1.20.1-47.1.106/forge-1.20.1-47.1.106-installer.jar",
        ),
    ],
)
def test_installer_urls(loader, url):
    assert loader.installer_url() == url


@pytest.mark.parametrize("path", PROFILE_FIXTURES, ids=lambda p: p.stem)
def test_real_profiles_resolve_every_client_processor(path, tmp_path):
    profile = InstallProfile.parse(json.loads(path.read_text(encoding="utf-8")))
    assert profile.spec in (0, 1)
    tokens = {
        key: value.client[1:-1] if value.client.startswith("'") else "resolved"
        for key, value in profile.data.items()
    }
    tokens.update(
        SIDE="client",
        MINECRAFT_JAR="client.jar",
        MINECRAFT_VERSION=profile.minecraft,
        ROOT="root",
        INSTALLER="installer.jar",
        LIBRARY_DIR="libraries",
    )
    variables = Variables(tmp_path, tokens)
    client = profile.client_processors()
    assert client
    for processor in client:
        maven_path(processor.jar)
        for coord in processor.classpath:
            maven_path(coord)
        for arg in processor.args:
            assert "{" not in variables.resolve(arg)
        for key, value in processor.outputs.items():
            variables.resolve(key)
            resolved = variables.resolve(value)
            assert "'" not in resolved
            assert len(resolved) == 40


def test_legacy_profile_is_rejected():
    with pytest.raises(UnsupportedError):
        InstallProfile.parse({"install": {}, "versionInfo": {}})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("{A}", "alpha"),
        ("--x={A}/{B}", "--x=alpha/bravo"),
        ("'{A}'", "{A}"),
        (r"\{A\}", "{A}"),
        ("plain", "plain"),
    ],
)
def test_replace_tokens(value, expected):
    assert replace_tokens({"A": "alpha", "B": "bravo"}, value) == expected


@pytest.mark.parametrize("value", ["{MISSING}", "{A", "'a", "a\\"])
def test_replace_tokens_rejects_bad_patterns(value):
    with pytest.raises(LoaderError):
        replace_tokens({"A": "alpha"}, value)


class FakePopen:
    """Stands in for subprocess.Popen so no external jar is executed."""

    instances: list["FakePopen"] = []
    on_run = None
    returncode_value = 0
    stdout_value = ""
    block = False

    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.returncode = None
        self.terminated = False
        FakePopen.instances.append(self)

    def communicate(self, timeout=None):
        if FakePopen.block and not self.terminated:
            raise subprocess.TimeoutExpired(self.command, timeout)
        if FakePopen.on_run:
            FakePopen.on_run(self.command)
        self.returncode = FakePopen.returncode_value
        return FakePopen.stdout_value, None

    def terminate(self):
        self.terminated = True


@pytest.fixture
def popen(monkeypatch):
    FakePopen.instances = []
    FakePopen.on_run = None
    FakePopen.returncode_value = 0
    FakePopen.stdout_value = ""
    FakePopen.block = False
    monkeypatch.setattr(processors_module.subprocess, "Popen", FakePopen)
    return FakePopen


def variables_for(tmp_path, tokens=None):
    return Variables(tmp_path / "libraries", {"OUT": str(tmp_path / "out.jar"), **(tokens or {})})


def tool_processor(tmp_path, outputs=None):
    libraries = tmp_path / "libraries"
    write_jar(libraries / maven_path("demo:tool:1"), "demo.Tool")
    write_jar(libraries / maven_path("demo:dep:1"))
    return Processor(
        jar="demo:tool:1",
        classpath=["demo:dep:1"],
        args=["--output", "{OUT}", "[demo:dep:1]"],
        outputs=outputs or {},
    )


def run(tmp_path, processor, tokens=None, **kwargs):
    run_processors(
        [processor], variables_for(tmp_path, tokens), tmp_path / "java", tmp_path / "libraries", **kwargs
    )


def test_processor_command(tmp_path, popen):
    run(tmp_path, tool_processor(tmp_path))
    command = popen.instances[0].command
    assert command[1] == "-cp"
    assert command[3] == "demo.Tool"
    assert command[4:6] == ["--output", str(tmp_path / "out.jar")]
    assert command[6] == str(tmp_path / "libraries" / maven_path("demo:dep:1"))


def test_processor_skipped_when_outputs_valid(tmp_path, popen):
    (tmp_path / "out.jar").write_bytes(b"done")
    run(tmp_path, tool_processor(tmp_path, {"{OUT}": "{SHA}"}), {"SHA": sha1(b"done")})
    assert popen.instances == []


def test_processor_reruns_and_replaces_bad_output(tmp_path, popen):
    out = tmp_path / "out.jar"
    out.write_bytes(b"stale")
    popen.on_run = lambda command: out.write_bytes(b"done")
    run(tmp_path, tool_processor(tmp_path, {"{OUT}": "{SHA}"}), {"SHA": sha1(b"done")})
    assert out.read_bytes() == b"done"


def test_failure_stops_and_reports_output(tmp_path, popen):
    popen.returncode_value = 3
    popen.stdout_value = "boom\n"
    processor = tool_processor(tmp_path)
    with pytest.raises(ProcessorError, match="boom"):
        run_processors(
            [processor, processor], variables_for(tmp_path), tmp_path / "java", tmp_path / "libraries"
        )
    assert len(popen.instances) == 1


def test_output_hash_mismatch_fails(tmp_path, popen):
    out = tmp_path / "out.jar"
    popen.on_run = lambda command: out.write_bytes(b"wrong")
    with pytest.raises(ProcessorError, match="Hash mismatch"):
        run(tmp_path, tool_processor(tmp_path, {"{OUT}": "{SHA}"}), {"SHA": sha1(b"done")})
    assert not out.exists()


def test_missing_output_fails(tmp_path, popen):
    with pytest.raises(ProcessorError, match="did not produce"):
        run(tmp_path, tool_processor(tmp_path, {"{OUT}": "{SHA}"}), {"SHA": sha1(b"done")})


def test_zlib_ng_accepts_valid_jar(tmp_path, popen, monkeypatch):
    monkeypatch.setattr(processors_module, "uses_zlib_ng", lambda: True)
    out = tmp_path / "out.jar"
    popen.on_run = lambda command: write_jar(out)
    run(tmp_path, tool_processor(tmp_path, {"{OUT}": "{SHA}"}), {"SHA": "0" * 40})
    assert out.exists()


def test_cancel_terminates_running_processor(tmp_path, popen, monkeypatch):
    popen.block = True
    token = ms.CancelToken()
    processor = tool_processor(tmp_path)
    monkeypatch.setattr(token, "check", lambda: None)
    token.cancel()
    with pytest.raises(Cancelled):
        run(tmp_path, processor, cancel=token)
    assert popen.instances[0].terminated


def test_missing_java_is_reported(tmp_path, monkeypatch):
    def missing(command, **kwargs):
        raise FileNotFoundError("java")

    monkeypatch.setattr(processors_module.subprocess, "Popen", missing)
    with pytest.raises(ProcessorError, match="Cannot run"):
        run(tmp_path, tool_processor(tmp_path))


def test_main_class_is_required(tmp_path, popen):
    processor = tool_processor(tmp_path)
    jar = tmp_path / "libraries" / maven_path("demo:tool:1")
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    with pytest.raises(ProcessorError, match="no Main-Class"):
        run(tmp_path, processor)


LOADER = Forge("36.2.42", "1.16.5", FORGE_MAVEN)
VERSION_ID = "1.16.5-forge-36.2.42"
BARE_JAR = "net/minecraftforge/forge/1.16.5-36.2.42/forge-1.16.5-36.2.42.jar"
UNIVERSAL_JAR = "net/minecraftforge/forge/1.16.5-36.2.42/forge-1.16.5-36.2.42-universal.jar"
PATCH = {
    "jar": "demo:tool:1",
    "classpath": [],
    "args": ["--input", "{BINPATCH}", "--out", "{PATCHED}", "--jar", "{MINECRAFT_JAR}"],
    "outputs": {"{PATCHED}": "{PATCHED_SHA}"},
}


def installer_bytes(tmp_path, processors=(), minecraft="1.16.5"):
    def artifact(path, url=""):
        return {"artifact": {"path": path, "url": url, "sha1": "", "size": 0}}

    profile = {
        "spec": 0,
        "version": VERSION_ID,
        "minecraft": minecraft,
        "json": "/version.json",
        "libraries": [
            {"name": "net.minecraftforge:forge:1.16.5-36.2.42:universal", "downloads": artifact(UNIVERSAL_JAR)},
            {
                "name": "demo:tool:1",
                "downloads": artifact(maven_path("demo:tool:1"), "https://libs.test/tool.jar"),
            },
        ],
        "processors": list(processors),
        "data": {
            "BINPATCH": {"client": "/data/client.lzma", "server": "/data/server.lzma"},
            "PATCHED": {"client": "[demo:patched:1]", "server": "[demo:patched:1:server]"},
            "PATCHED_SHA": {"client": f"'{sha1(b'patched')}'", "server": "'x'"},
        },
    }
    version = {
        "id": VERSION_ID,
        "inheritsFrom": "1.16.5",
        "libraries": [
            {"name": "net.minecraftforge:forge:1.16.5-36.2.42", "downloads": artifact(BARE_JAR)}
        ],
    }
    return write_zip(
        tmp_path / "built" / "installer.jar",
        {
            "install_profile.json": json.dumps(profile),
            "version.json": json.dumps(version),
            f"maven/{UNIVERSAL_JAR}": b"universal",
            f"maven/{BARE_JAR}": b"bare",
            "data/client.lzma": b"patch-data",
        },
    ).read_bytes()


def stub_installer(tmp_path, processors=(), minecraft="1.16.5"):
    body = installer_bytes(tmp_path, processors, minecraft)
    url = LOADER.installer_url()
    responses.get(f"{url}.sha1", body=sha1(body))
    responses.get(url, body=body)
    tool = write_jar(tmp_path / "built" / "tool.jar", "demo.Tool")
    responses.get("https://libs.test/tool.jar", body=tool.read_bytes())


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    game = GameDir(tmp_path / "mc")
    game.write_version(
        "1.16.5",
        {
            "id": "1.16.5",
            "javaVersion": {"component": "java-runtime-delta"},
            "downloads": {"client": {"url": "https://x.test", "sha1": sha1(b"client"), "size": 6}},
        },
    )
    game.client_jar("1.16.5").write_bytes(b"client")
    return game


def patched(game):
    path = game.library("demo:patched:1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"patched")


@responses.activate
def test_forge_install_end_to_end(game, tmp_path, session, popen):
    stub_installer(tmp_path, [PATCH])
    runtime = fake_runtime(game.path / "runtime", "java-runtime-delta")
    seen = {}

    def on_run(command):
        seen["data"] = Path(command[command.index("--input") + 1]).read_bytes()
        patched(game)

    popen.on_run = on_run
    version_id = LOADER.install(game, cache_dir=tmp_path / "cache", session=session)

    assert version_id == VERSION_ID
    command = popen.instances[0].command
    assert command[0] == str(runtime)
    assert seen["data"] == b"patch-data"
    assert str(game.client_jar("1.16.5")) in command
    assert (game.libraries_dir / UNIVERSAL_JAR).read_bytes() == b"universal"
    assert (game.libraries_dir / BARE_JAR).read_bytes() == b"bare"
    assert game.version(VERSION_ID).inherits_from == "1.16.5"
    assert LOADER.is_installed(game, session=session, cache_dir=tmp_path / "cache")


@responses.activate
def test_explicit_java_is_used(game, tmp_path, session, popen):
    stub_installer(tmp_path, [PATCH])
    popen.on_run = lambda command: patched(game)
    LOADER.install(game, java=tmp_path / "my-java", cache_dir=tmp_path / "cache", session=session)
    assert popen.instances[0].command[0] == str(tmp_path / "my-java")


@responses.activate
def test_failed_patch_does_not_register_version(game, tmp_path, session, popen):
    stub_installer(tmp_path, [PATCH])
    fake_runtime(game.path / "runtime", "java-runtime-delta")
    popen.returncode_value = 1
    with pytest.raises(ProcessorError):
        LOADER.install(game, cache_dir=tmp_path / "cache", session=session)
    assert not game.has_version(VERSION_ID)


@responses.activate
def test_mismatched_installer_is_rejected(game, tmp_path, session, popen):
    stub_installer(tmp_path, minecraft="1.20.1")
    with pytest.raises(LoaderError):
        LOADER.install(game, cache_dir=tmp_path / "cache", session=session)


@responses.activate
def test_falls_back_to_other_runtime_then_downloads(game, tmp_path, session, popen, monkeypatch):
    stub_installer(tmp_path, [PATCH])
    other = fake_runtime(game.path / "runtime", "java-runtime-gamma")
    required = tmp_path / "required-java"
    monkeypatch.setattr(
        ms.java, "download", lambda component, **kw: ms.java.JavaRuntime(component, required)
    )

    def on_run(command):
        if command[0] == str(required):
            popen.returncode_value = 0
            patched(game)
        else:
            popen.returncode_value = 1

    popen.on_run = on_run
    LOADER.install(game, cache_dir=tmp_path / "cache", session=session)
    assert [item.command[0] for item in popen.instances] == [str(other), str(required)]


@responses.activate
def test_exact_runtime_failure_does_not_download(game, tmp_path, session, popen, monkeypatch):
    stub_installer(tmp_path, [PATCH])
    fake_runtime(game.path / "runtime", "java-runtime-delta")
    popen.returncode_value = 1

    def fail(*args, **kwargs):
        raise AssertionError("must not download")

    monkeypatch.setattr(ms.java, "download", fail)
    with pytest.raises(ProcessorError):
        LOADER.install(game, cache_dir=tmp_path / "cache", session=session)


@responses.activate
def test_installer_without_sha1_file(game, tmp_path, session, popen):
    url = LOADER.installer_url()
    responses.get(f"{url}.sha1", status=404)
    responses.get(url, body=installer_bytes(tmp_path))
    tool = write_jar(tmp_path / "built" / "tool.jar")
    responses.get("https://libs.test/tool.jar", body=tool.read_bytes())
    assert LOADER.install(game, cache_dir=tmp_path / "cache", session=session) == VERSION_ID


def test_malformed_installer(tmp_path):
    path = tmp_path / "bad.jar"
    path.write_bytes(b"not a zip")
    with pytest.raises(LoaderError):
        InstallerJar(path)


FABRIC = Fabric("0.16.10", "1.16.5", "https://meta.test/v2")
FABRIC_URL = "https://meta.test/v2/versions/loader/1.16.5/0.16.10/profile/json"


@responses.activate
def test_fabric_install(game, session):
    responses.get(
        FABRIC_URL,
        json={
            "id": "fabric-loader-0.16.10-1.16.5",
            "libraries": [
                {"name": "net.fabricmc:loader:1", "url": "https://maven.test/", "sha1": sha1(b"lib")},
                {"name": "org:other:2", "url": "https://maven.test"},
            ],
        },
    )
    responses.get("https://maven.test/net/fabricmc/loader/1/loader-1.jar", body=b"lib")
    responses.get("https://maven.test/org/other/2/other-2.jar", body=b"other")

    version_id = FABRIC.install(game, session=session)

    assert version_id == "fabric-loader-0.16.10-1.16.5"
    assert game.library("net.fabricmc:loader:1").read_bytes() == b"lib"
    assert FABRIC.is_installed(game, session=session)


def test_fabric_and_quilt_use_their_own_services():
    assert "meta.fabricmc.net/v2/versions/loader/1.21/1/" in Fabric("1", "1.21").profile_url()
    assert "meta.quiltmc.org/v3/versions/loader/1.21/1/" in Quilt("1", "1.21").profile_url()
