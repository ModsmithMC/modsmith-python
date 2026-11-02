import hashlib
import json
import zipfile

import pytest
import responses

from conftest import (
    PROFILE_FIXTURES,
    FakeRunner,
    fake_java,
    library_path,
    sha1,
    write_installer,
    write_jar,
)
from cursecraft.core.errors import (
    LoaderInstallError,
    ProcessorError,
    UnsupportedError,
)
from cursecraft.core.paths import maven_path
from cursecraft.core.steps import run_steps
from cursecraft.loaders import LoaderSpec
from cursecraft.loaders import forge_like as forge_module
from cursecraft.loaders import processors as processors_module
from cursecraft.loaders.fabric import FabricInstaller
from cursecraft.loaders.forge_like import ForgeInstaller, NeoForgeInstaller
from cursecraft.loaders.install_profile import (
    InstallerJar,
    InstallProfile,
    Processor,
    Variables,
    replace_tokens,
)
from cursecraft.loaders.processors import run_processors

FORGE_MAVEN = "https://forge.test"
NEO_MAVEN = "https://neo.test/releases"


@pytest.mark.parametrize(
    ("loader_id", "mc", "expected"),
    [
        ("forge-47.3.0", "1.20.1", ("forge", "47.3.0")),
        ("neoforge-21.1.233", "1.21.1", ("neoforge", "21.1.233")),
        ("neoforge-1.20.1-47.1.106", "1.20.1", ("neoforge", "47.1.106")),
        ("fabric-0.16.10", "1.21.1", ("fabric", "0.16.10")),
    ],
)
def test_parse_loader_spec(loader_id, mc, expected):
    spec = LoaderSpec.parse(loader_id, mc)
    assert (spec.kind, spec.version, spec.mc_version) == (*expected, mc)


@pytest.mark.parametrize("loader_id", ["quilt-0.26.0", "forge", "liteloader-1"])
def test_parse_rejects_unsupported_loaders(loader_id):
    with pytest.raises(UnsupportedError):
        LoaderSpec.parse(loader_id, "1.20.1")


@pytest.mark.parametrize(
    ("installer", "spec", "url"),
    [
        (
            ForgeInstaller(FORGE_MAVEN),
            LoaderSpec("forge", "47.3.0", "1.20.1"),
            "https://forge.test/net/minecraftforge/forge/1.20.1-47.3.0/forge-1.20.1-47.3.0-installer.jar",
        ),
        (
            NeoForgeInstaller(NEO_MAVEN),
            LoaderSpec("neoforge", "21.1.233", "1.21.1"),
            "https://neo.test/releases/net/neoforged/neoforge/21.1.233/neoforge-21.1.233-installer.jar",
        ),
        (
            NeoForgeInstaller(NEO_MAVEN),
            LoaderSpec("neoforge", "47.1.106", "1.20.1"),
            "https://neo.test/releases/net/neoforged/forge/1.20.1-47.1.106/forge-1.20.1-47.1.106-installer.jar",
        ),
    ],
)
def test_installer_urls(installer, spec, url):
    assert installer.installer_url(spec) == url


@pytest.mark.parametrize("path", PROFILE_FIXTURES, ids=lambda p: p.stem)
def test_real_profiles_resolve_every_client_processor(path, tmp_path):
    profile = InstallProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert profile.spec in (0, 1)

    tokens = {
        key: value[1:-1] if value.startswith("'") else "resolved"
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
    assert all("server" not in (p.sides or []) or "client" in p.sides for p in client)


def test_legacy_profile_is_rejected():
    with pytest.raises(UnsupportedError):
        InstallProfile.from_dict({"install": {}, "versionInfo": {}})


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
    with pytest.raises(LoaderInstallError):
        replace_tokens({"A": "alpha"}, value)


def make_variables(tmp_path, tokens=None):
    return Variables(tmp_path / "libraries", {"OUT": str(tmp_path / "out.jar"), **(tokens or {})})


def make_processor(tmp_path, outputs=None, args=None, sides=None):
    libraries = tmp_path / "libraries"
    write_jar(libraries / maven_path("demo:tool:1"), "demo.Tool")
    write_jar(libraries / maven_path("demo:dep:1"))
    return Processor(
        jar="demo:tool:1",
        classpath=["demo:dep:1"],
        args=args or ["--output", "{OUT}", "[demo:dep:1]"],
        outputs=outputs or {},
        sides=sides,
    )


def run(tmp_path, processor, tokens=None, runner=None):
    runner = runner or FakeRunner()
    run_processors(
        [processor],
        make_variables(tmp_path, tokens),
        tmp_path / "java",
        tmp_path / "libraries",
        runner=runner,
    )
    return runner


def test_processor_command_uses_main_class_and_resolved_args(tmp_path):
    runner = run(tmp_path, make_processor(tmp_path))
    command = runner.commands[0]
    assert command[1] == "-cp"
    assert command[3] == "demo.Tool"
    assert command[4:6] == ["--output", str(tmp_path / "out.jar")]
    assert command[6] == str(tmp_path / "libraries" / maven_path("demo:dep:1"))


def test_processor_skipped_when_outputs_are_valid(tmp_path):
    out = tmp_path / "out.jar"
    out.write_bytes(b"done")
    processor = make_processor(tmp_path, {"{OUT}": "{SHA}"})
    runner = run(tmp_path, processor, {"SHA": sha1(b"done")})
    assert runner.commands == []


def test_processor_reruns_and_replaces_bad_output(tmp_path):
    out = tmp_path / "out.jar"
    out.write_bytes(b"stale")
    processor = make_processor(tmp_path, {"{OUT}": "{SHA}"})
    runner = FakeRunner(lambda command: out.write_bytes(b"done"))
    run(tmp_path, processor, {"SHA": sha1(b"done")}, runner)
    assert len(runner.commands) == 1
    assert out.read_bytes() == b"done"


def test_processor_failure_stops_and_reports_output(tmp_path):
    runner = FakeRunner(returncode=3, stdout="boom\n")
    with pytest.raises(ProcessorError, match="boom"):
        run_processors(
            [make_processor(tmp_path), make_processor(tmp_path)],
            make_variables(tmp_path),
            tmp_path / "java",
            tmp_path / "libraries",
            runner=runner,
        )
    assert len(runner.commands) == 1


def test_output_hash_mismatch_fails_and_removes_file(tmp_path):
    out = tmp_path / "out.jar"
    processor = make_processor(tmp_path, {"{OUT}": "{SHA}"})
    runner = FakeRunner(lambda command: out.write_bytes(b"wrong"))
    with pytest.raises(ProcessorError, match="Hash mismatch"):
        run(tmp_path, processor, {"SHA": sha1(b"done")}, runner)
    assert not out.exists()


def test_missing_output_fails(tmp_path):
    processor = make_processor(tmp_path, {"{OUT}": "{SHA}"})
    with pytest.raises(ProcessorError, match="did not produce"):
        run(tmp_path, processor, {"SHA": sha1(b"done")})


def test_zlib_ng_accepts_valid_jar_with_other_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(processors_module, "uses_zlib_ng", lambda: True)
    out = tmp_path / "out.jar"
    processor = make_processor(tmp_path, {"{OUT}": "{SHA}"})
    run(tmp_path, processor, {"SHA": "0" * 40}, FakeRunner(lambda c: write_jar(out)))
    assert out.exists()


def test_missing_java_is_a_processor_error(tmp_path):
    def missing(command, **kwargs):
        raise FileNotFoundError("java")

    with pytest.raises(ProcessorError, match="Cannot run"):
        run(tmp_path, make_processor(tmp_path), runner=missing)


def test_main_class_is_required(tmp_path):
    processor = make_processor(tmp_path)
    write_jar(tmp_path / "libraries" / maven_path("demo:tool:1"), "")
    jar = tmp_path / "libraries" / maven_path("demo:tool:1")
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    with pytest.raises(ProcessorError, match="no Main-Class"):
        run(tmp_path, processor)


FORGE_SPEC = LoaderSpec("forge", "36.2.42", "1.16.5")
FORGE_URL = ForgeInstaller(FORGE_MAVEN).installer_url(FORGE_SPEC)
VERSION_ID = "1.16.5-forge-36.2.42"
BARE_JAR = "net/minecraftforge/forge/1.16.5-36.2.42/forge-1.16.5-36.2.42.jar"
UNIVERSAL_JAR = "net/minecraftforge/forge/1.16.5-36.2.42/forge-1.16.5-36.2.42-universal.jar"


def forge_installer_bytes(tmp_path, processors=None):
    profile = {
        "spec": 0,
        "version": VERSION_ID,
        "minecraft": "1.16.5",
        "json": "/version.json",
        "libraries": [
            {
                "name": "net.minecraftforge:forge:1.16.5-36.2.42:universal",
                "downloads": {"artifact": {"path": UNIVERSAL_JAR, "url": "", "sha1": "", "size": 0}},
            },
            {
                "name": "demo:tool:1",
                "downloads": {
                    "artifact": {
                        "path": maven_path("demo:tool:1"),
                        "url": "https://libs.test/tool.jar",
                        "sha1": "",
                        "size": 0,
                    }
                },
            },
        ],
        "processors": processors or [],
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
            {
                "name": "net.minecraftforge:forge:1.16.5-36.2.42",
                "downloads": {"artifact": {"path": BARE_JAR, "url": "", "sha1": "", "size": 0}},
            }
        ],
    }
    installer = write_installer(
        tmp_path / "built" / "installer.jar",
        profile,
        version,
        {
            f"maven/{UNIVERSAL_JAR}": b"universal",
            f"maven/{BARE_JAR}": b"bare",
            "data/client.lzma": b"patch-data",
        },
    )
    return installer.read_bytes()


def stub_forge(tmp_path, processors=None):
    body = forge_installer_bytes(tmp_path, processors)
    responses.get(f"{FORGE_URL}.sha1", body=sha1(body))
    responses.get(FORGE_URL, body=body)
    tool = tmp_path / "built" / "tool.jar"
    write_jar(tool, "demo.Tool")
    responses.get("https://libs.test/tool.jar", body=tool.read_bytes())


def stub_mc(ctx):
    client = ctx.versions.client_jar("1.16.5")
    client.parent.mkdir(parents=True)
    client.write_bytes(b"client")
    ctx.versions.version_file("1.16.5").write_text(
        json.dumps(
            {
                "javaVersion": {"component": "java-runtime-delta"},
                "downloads": {
                    "client": {"url": "https://x.test", "sha1": sha1(b"client"), "size": 6}
                },
            }
        ),
        encoding="utf-8",
    )


def install(ctx, spec=FORGE_SPEC):
    plan = ForgeInstaller(FORGE_MAVEN).prepare(spec, ctx)
    run_steps(plan.steps)
    return plan


PATCH_PROCESSOR = {
    "jar": "demo:tool:1",
    "classpath": [],
    "args": ["--input", "{BINPATCH}", "--out", "{PATCHED}", "--jar", "{MINECRAFT_JAR}"],
    "outputs": {"{PATCHED}": "{PATCHED_SHA}"},
}


def patched_output(ctx):
    return ctx.libraries_dir / maven_path("demo:patched:1")


@pytest.fixture
def fake_processors(monkeypatch):
    runner = FakeRunner()
    original = run_processors

    def wrapped(processors, variables, java, libraries_dir, emit):
        return original(processors, variables, java, libraries_dir, emit, runner=runner)

    monkeypatch.setattr(forge_module, "run_processors", wrapped)
    return runner


@responses.activate
def test_forge_install_end_to_end(ctx, tmp_path, fake_processors):
    stub_forge(tmp_path, [PATCH_PROCESSOR])
    stub_mc(ctx)
    java = fake_java(ctx.root / "runtime", "java-runtime-delta")
    seen = {}

    def on_run(command):
        data = command[command.index("--input") + 1]
        seen["data"] = open(data, "rb").read()
        path = patched_output(ctx)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"patched")

    fake_processors.on_run = on_run
    plan = install(ctx)

    assert plan.version_id == VERSION_ID
    assert fake_processors.commands[0][0] == str(java)
    assert seen["data"] == b"patch-data"
    assert str(ctx.versions.client_jar("1.16.5")) in fake_processors.commands[0]
    assert (ctx.libraries_dir / UNIVERSAL_JAR).read_bytes() == b"universal"
    assert (ctx.libraries_dir / BARE_JAR).read_bytes() == b"bare"
    assert json.loads(ctx.version_file(VERSION_ID).read_text(encoding="utf-8"))["id"] == VERSION_ID


@responses.activate
def test_forge_second_install_has_no_steps(ctx, tmp_path, fake_processors):
    stub_forge(tmp_path)
    stub_mc(ctx)
    install(ctx)
    assert ForgeInstaller(FORGE_MAVEN).prepare(FORGE_SPEC, ctx).steps == []


@responses.activate
def test_interrupted_patch_does_not_register_version(ctx, tmp_path, fake_processors):
    stub_forge(tmp_path, [PATCH_PROCESSOR])
    stub_mc(ctx)
    fake_java(ctx.root / "runtime", "java-runtime-delta")
    fake_processors.returncode = 1
    with pytest.raises(ProcessorError):
        install(ctx)
    assert not ctx.version_file(VERSION_ID).exists()


@responses.activate
def test_forge_falls_back_then_downloads_required_java(
    ctx, tmp_path, fake_processors, monkeypatch
):
    stub_forge(tmp_path, [PATCH_PROCESSOR])
    stub_mc(ctx)
    other = fake_java(ctx.root / "runtime", "java-runtime-gamma")
    required = tmp_path / "required" / "java"
    monkeypatch.setattr(ctx.java, "download", lambda component, emit: required)

    def on_run(command):
        if command[0] == str(required):
            path = patched_output(ctx)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"patched")
        else:
            fake_processors.returncode = 1

    fake_processors.on_run = on_run

    original = forge_module.run_processors

    def flaky(processors, variables, java, libraries_dir, emit):
        fake_processors.returncode = 0
        return original(processors, variables, java, libraries_dir, emit)

    monkeypatch.setattr(forge_module, "run_processors", flaky)
    install(ctx)
    assert [c[0] for c in fake_processors.commands] == [str(other), str(required)]


@responses.activate
def test_exact_java_failure_does_not_download(ctx, tmp_path, fake_processors, monkeypatch):
    stub_forge(tmp_path, [PATCH_PROCESSOR])
    stub_mc(ctx)
    fake_java(ctx.root / "runtime", "java-runtime-delta")
    fake_processors.returncode = 1

    def fail(component, emit):
        raise AssertionError("must not download")

    monkeypatch.setattr(ctx.java, "download", fail)
    with pytest.raises(ProcessorError):
        install(ctx)


@responses.activate
def test_installer_without_sha1_file_still_installs(ctx, tmp_path, fake_processors):
    body = forge_installer_bytes(tmp_path)
    responses.get(f"{FORGE_URL}.sha1", status=404)
    responses.get(FORGE_URL, body=body)
    tool = write_jar(tmp_path / "built" / "tool.jar")
    responses.get("https://libs.test/tool.jar", body=tool.read_bytes())
    stub_mc(ctx)
    assert install(ctx).version_id == VERSION_ID


def test_malformed_installer_is_reported(tmp_path):
    path = tmp_path / "bad.jar"
    path.write_bytes(b"not a zip")
    with pytest.raises(LoaderInstallError):
        InstallerJar(path)


FABRIC_SPEC = LoaderSpec("fabric", "0.16.10", "1.21.1")
FABRIC_META = "https://meta.test/v2/versions/loader/1.21.1/0.16.10/profile/json"


@responses.activate
def test_fabric_install_uses_official_id_and_library_hashes(ctx):
    responses.get(
        FABRIC_META,
        json={
            "id": "fabric-loader-0.16.10-1.21.1",
            "inheritsFrom": "1.21.1",
            "libraries": [
                {
                    "name": "net.fabricmc:loader:1",
                    "url": "https://maven.test/",
                    "md5": hashlib.md5(b"lib").hexdigest(),
                },
                {"name": "org:other:2", "url": "https://maven.test"},
            ],
        },
    )
    responses.get("https://maven.test/net/fabricmc/loader/1/loader-1.jar", body=b"lib")
    responses.get("https://maven.test/org/other/2/other-2.jar", body=b"other")

    plan = FabricInstaller("https://meta.test").prepare(FABRIC_SPEC, ctx)
    run_steps(plan.steps)

    assert plan.version_id == "fabric-loader-0.16.10-1.21.1"
    assert library_path(ctx.root, "net.fabricmc:loader:1").read_bytes() == b"lib"
    assert ctx.version_file(plan.version_id).is_file()
    assert FabricInstaller("https://meta.test").prepare(FABRIC_SPEC, ctx).steps == []


@responses.activate
def test_fabric_versions_for_different_mc_do_not_collide(ctx):
    for mc in ("1.20.1", "1.21.1"):
        responses.get(
            f"https://meta.test/v2/versions/loader/{mc}/0.16.10/profile/json",
            json={"id": f"fabric-loader-0.16.10-{mc}", "libraries": []},
        )
    installer = FabricInstaller("https://meta.test")
    first = installer.prepare(LoaderSpec("fabric", "0.16.10", "1.20.1"), ctx)
    run_steps(first.steps)
    second = installer.prepare(LoaderSpec("fabric", "0.16.10", "1.21.1"), ctx)
    assert second.version_id != first.version_id
    assert second.steps
