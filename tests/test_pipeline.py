import json
import zipfile

import pytest
import responses

from conftest import sha1
from cursecraft import CurseCraft, Settings
from cursecraft.core.errors import (
    InstanceError,
    LauncherError,
    LauncherRunningError,
    ManualDownloadRequired,
    SourceError,
)
from cursecraft.core.events import Message
from cursecraft.core.steps import FunctionStep
from cursecraft.loaders import LoaderPlan
from cursecraft.pipeline import modpack as modpack_module
from cursecraft.pipeline.modpack import slugify
from cursecraft.pipeline.overrides import apply_overrides, remove_stale, safe_relative
from cursecraft.sources.base import (
    PackEntry,
    PackFile,
    PackManifest,
    Project,
    ResolvedFile,
)

CDN = "https://cdn.test"


def build_pack(path, overrides=None, loader="forge-47.3.0", name="Test Pack"):
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifestType": "minecraftModpack",
        "name": name,
        "version": "1.0",
        "overrides": "overrides",
        "minecraft": {
            "version": "1.20.1",
            "recommendedRam": 4096,
            "modLoaders": [{"id": loader, "primary": True}],
        },
        "files": [],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in (overrides or {}).items():
            archive.writestr(f"overrides/{name}", data)
    return path


class FakeSource:
    name = "curseforge"

    def __init__(self, files, pack_bytes):
        self.files = files
        self.pack_bytes = pack_bytes
        self.pack_id = 100
        self.project = Project(
            "curseforge", 7, "test-pack", "Test Pack", icon_url=f"{CDN}/icon.png"
        )

    def search(self, text, game_version=None, index=0):
        raise NotImplementedError

    def get_project(self, ref):
        return self.project

    def latest_pack_file(self, project, allow_prerelease=False):
        return PackFile(
            self.pack_id, 7, f"Test Pack {self.pack_id}", f"pack-{self.pack_id}.zip",
            f"{CDN}/pack-{self.pack_id}.zip", sha1(self.pack_bytes), "sha1", len(self.pack_bytes),
        )

    def read_manifest(self, data):
        minecraft = data["minecraft"]
        return PackManifest(
            data["name"], data["version"], minecraft["version"],
            minecraft["modLoaders"][0]["id"], data["overrides"], minecraft["recommendedRam"],
            [PackEntry(1, file.file_id) for file in self.files],
        )

    def resolve_files(self, manifest):
        return list(self.files)


class FakeInstaller:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def prepare(self, spec, ctx):
        self.calls += 1

        def write(emit):
            if self.fail:
                raise LauncherError("boom")
            ctx.write_version("1.20.1-forge-47.3.0", {"id": "1.20.1-forge-47.3.0"})

        return LoaderPlan("1.20.1-forge-47.3.0", [FunctionStep("Install loader", write)])


def mod(file_id, data, url=True):
    name = f"mod-{file_id}.jar"
    return ResolvedFile(
        1, file_id, name, "mods",
        f"{CDN}/{name}" if url else None,
        sha1(data), "sha1", len(data),
        None if url else f"https://example.test/{file_id}",
    ), data


def stub_mod(file, data):
    if file.url:
        responses.get(file.url, body=data)


def stub_pack(source):
    responses.get(f"{CDN}/pack-{source.pack_id}.zip", body=source.pack_bytes)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(modpack_module, "is_launcher_running", lambda: False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    minecraft = tmp_path / "minecraft"
    minecraft.mkdir()
    (minecraft / "launcher_profiles.json").write_text(
        json.dumps({"profiles": {"existing": {"name": "Keep"}}}), encoding="utf-8"
    )
    client = minecraft / "versions" / "1.20.1"
    client.mkdir(parents=True)
    (client / "1.20.1.jar").write_bytes(b"client")
    (client / "1.20.1.json").write_text(
        json.dumps(
            {"downloads": {"client": {"url": f"{CDN}/client", "sha1": sha1(b"client"), "size": 6}}}
        ),
        encoding="utf-8",
    )
    return tmp_path


def make_app(env, source, installer=None):
    settings = Settings(
        minecraft_dir=env / "minecraft",
        cache_dir=env / "cache",
        manual_download_dir=env / "downloads",
    )
    return CurseCraft(
        settings,
        sources={"curseforge": source},
        installers={"forge": installer or FakeInstaller()},
    )


def pack_bytes(env, overrides=None, name="pack.zip", **kwargs):
    return build_pack(env / "built" / name, overrides, **kwargs).read_bytes()


def profiles(env):
    return json.loads(
        (env / "minecraft" / "launcher_profiles.json").read_text(encoding="utf-8")
    )["profiles"]


@responses.activate
def test_full_install(env):
    file, data = mod(1, b"mod-one")
    source = FakeSource([file], pack_bytes(env, {"config/a.toml": "a=1"}))
    stub_mod(file, data)
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", body=b"png", content_type="image/png")
    app = make_app(env, source)

    plan = app.plan_install(7)
    assert plan.download_size == len(data)
    assert plan.loader.kind == "forge"
    record = app.install(plan)

    game_dir = env / "minecraft" / "cursecraft" / "instances" / "test-pack"
    assert (game_dir / "mods" / "mod-1.jar").read_bytes() == data
    assert (game_dir / "config" / "a.toml").read_text() == "a=1"
    assert record.version_id == "1.20.1-forge-47.3.0"
    assert record.files == {"mods/mod-1.jar": sha1(data)}
    assert record.overrides == {"config/a.toml": sha1(b"a=1")}

    profile = profiles(env)["cursecraft-test-pack"]
    assert profile["gameDir"] == str(game_dir)
    assert profile["lastVersionId"] == "1.20.1-forge-47.3.0"
    assert profile["javaArgs"] == "-Xmx4096M"
    assert profile["icon"].startswith("data:image/png;base64,")
    assert "existing" in profiles(env)
    assert [item.slug for item in app.list_instances()] == ["test-pack"]


@responses.activate
def test_profile_survives_icon_failure(env):
    source = FakeSource([], pack_bytes(env))
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", status=404)
    app = make_app(env, source)
    app.install(app.plan_install(7))
    assert "icon" not in profiles(env)["cursecraft-test-pack"]


@responses.activate
def test_failed_install_can_resume(env):
    file, data = mod(1, b"mod-one")
    source = FakeSource([file], pack_bytes(env))
    stub_mod(file, data)
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", status=404)
    installer = FakeInstaller()
    installer.fail = True
    app = make_app(env, source, installer)

    plan = app.plan_install(7)
    with pytest.raises(LauncherError):
        app.install(plan)
    assert not app.instances.exists("test-pack")
    assert "cursecraft-test-pack" not in profiles(env)

    installer.fail = False
    app.install(app.plan_install(7))
    assert app.instances.exists("test-pack")
    mod_calls = [c for c in responses.calls if c.request.url.endswith("mod-1.jar")]
    assert len(mod_calls) == 1


@responses.activate
def test_already_installed_is_rejected(env):
    source = FakeSource([], pack_bytes(env))
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", status=404)
    app = make_app(env, source)
    app.install(app.plan_install(7))
    with pytest.raises(InstanceError):
        app.plan_install(7)


@responses.activate
def test_running_launcher_blocks_install(env, monkeypatch):
    source = FakeSource([], pack_bytes(env))
    stub_pack(source)
    app = make_app(env, source)
    plan = app.plan_install(7)
    monkeypatch.setattr(modpack_module, "is_launcher_running", lambda: True)
    with pytest.raises(LauncherRunningError):
        app.install(plan)


@responses.activate
def test_missing_launcher_profile_fails_before_downloading(env):
    file, _ = mod(1, b"mod-one")
    source = FakeSource([file], pack_bytes(env))
    stub_pack(source)
    (env / "minecraft" / "launcher_profiles.json").unlink()
    app = make_app(env, source)
    with pytest.raises(LauncherError):
        app.install(app.plan_install(7))
    assert not any("mod-1" in c.request.url for c in responses.calls)


@responses.activate
def test_manual_files_stop_install_with_instructions(env):
    file, data = mod(1, b"blocked", url=False)
    source = FakeSource([file], pack_bytes(env))
    stub_pack(source)
    app = make_app(env, source)
    plan = app.plan_install(7)
    assert plan.manual_files == [file]
    with pytest.raises(ManualDownloadRequired) as error:
        app.install(plan)
    item = error.value.items[0]
    assert item.file_name == "mod-1.jar"
    assert item.url == "https://example.test/1"


@responses.activate
def test_manual_file_from_downloads_is_verified_and_used(env):
    file, data = mod(1, b"blocked", url=False)
    source = FakeSource([file], pack_bytes(env))
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", status=404)
    downloads = env / "downloads"
    downloads.mkdir()
    (downloads / file.file_name).write_bytes(b"tampered")
    app = make_app(env, source)
    plan = app.plan_install(7)
    with pytest.raises(ManualDownloadRequired):
        app.install(plan)

    (downloads / file.file_name).write_bytes(data)
    record = app.install(plan)
    assert record.files == {"mods/mod-1.jar": sha1(data)}


@responses.activate
def test_update_replaces_managed_files_and_keeps_user_changes(env):
    old_file, old_data = mod(1, b"old-mod")
    source = FakeSource(
        [old_file],
        pack_bytes(env, {"config/keep.toml": "v1", "config/take.toml": "v1", "config/gone.toml": "v1"}),
    )
    stub_mod(old_file, old_data)
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", body=b"png")
    app = make_app(env, source)
    app.install(app.plan_install(7))

    game_dir = app.instances.game_dir("test-pack")
    (game_dir / "config" / "keep.toml").write_text("mine")
    (game_dir / "mods" / "user-added.jar").write_bytes(b"mine")
    (game_dir / "saves").mkdir()

    new_file, new_data = mod(2, b"new-mod")
    source.files = [new_file]
    source.pack_id = 101
    source.pack_bytes = pack_bytes(
        env, {"config/keep.toml": "v2", "config/take.toml": "v2"}, name="pack2.zip"
    )
    stub_mod(new_file, new_data)
    stub_pack(source)

    plan = app.plan_update("test-pack")
    assert plan.is_update
    events = []
    record = app.update(plan, events.append)

    assert not (game_dir / "mods" / "mod-1.jar").exists()
    assert (game_dir / "mods" / "mod-2.jar").read_bytes() == new_data
    assert (game_dir / "mods" / "user-added.jar").exists()
    assert (game_dir / "config" / "keep.toml").read_text() == "mine"
    assert (game_dir / "config" / "take.toml").read_text() == "v2"
    assert not (game_dir / "config" / "gone.toml").exists()
    assert record.kept_overrides == ["config/keep.toml"]
    assert record.file_id == 101
    assert record.installed_at <= record.updated_at
    assert any(isinstance(e, Message) and "keep.toml" in e.text for e in events)


@responses.activate
def test_update_returns_none_when_current(env):
    source = FakeSource([], pack_bytes(env))
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", status=404)
    app = make_app(env, source)
    app.install(app.plan_install(7))
    assert app.plan_update("test-pack") is None


@responses.activate
def test_uninstall_removes_instance_and_profile_only(env):
    source = FakeSource([], pack_bytes(env))
    stub_pack(source)
    responses.get(f"{CDN}/icon.png", status=404)
    app = make_app(env, source)
    app.install(app.plan_install(7))
    library = env / "minecraft" / "libraries" / "shared.jar"
    library.parent.mkdir()
    library.write_bytes(b"shared")

    app.uninstall("test-pack")
    assert not app.instances.game_dir("test-pack").exists()
    assert list(profiles(env)) == ["existing"]
    assert library.exists()


def test_uninstall_unknown_instance(env):
    with pytest.raises(InstanceError):
        make_app(env, FakeSource([], b"")).uninstall("nope")


@responses.activate
def test_local_import_cannot_update(env):
    responses.get(f"{CDN}/icon.png", status=404)
    archive = build_pack(env / "local" / "My Pack!.zip", {"a.txt": "x"}, name="My Pack!")
    source = FakeSource([], b"")
    app = make_app(env, source)
    plan = app.plan_local(archive)
    assert plan.slug == "my-pack"
    record = app.install(plan)
    assert record.source == "local"
    assert record.project_id is None
    with pytest.raises(InstanceError):
        app.plan_update("my-pack")


def test_invalid_local_file(env, tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"nope")
    with pytest.raises(SourceError):
        make_app(env, FakeSource([], b"")).plan_local(bad)


@pytest.mark.parametrize("name", ["../evil", "/etc/passwd", "a/../../b", "C:/x", "a\\b"])
def test_unsafe_paths_are_rejected(name):
    with pytest.raises(SourceError):
        safe_relative(name)


def test_override_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / "p.zip"
    with zipfile.ZipFile(archive, "w") as pack:
        pack.writestr("overrides/../../evil.txt", "x")
    with pytest.raises(SourceError):
        apply_overrides(archive, "overrides", tmp_path / "game")
    assert not (tmp_path / "evil.txt").exists()


def test_first_install_overwrites_leftovers(tmp_path):
    archive = build_pack(tmp_path / "p.zip", {"a.txt": "new"})
    game = tmp_path / "game"
    game.mkdir()
    (game / "a.txt").write_text("partial")
    result = apply_overrides(archive, "overrides", game)
    assert (game / "a.txt").read_text() == "new"
    assert result.kept == []


def test_remove_stale_keeps_modified_files(tmp_path):
    (tmp_path / "same").write_bytes(b"x")
    (tmp_path / "changed").write_bytes(b"mine")
    removed = remove_stale(
        tmp_path, {"same": sha1(b"x"), "changed": sha1(b"x"), "absent": "0"}, {}
    )
    assert removed == ["same"]
    assert (tmp_path / "changed").exists()


@pytest.mark.parametrize(
    ("name", "slug"),
    [("All The Mods 10", "all-the-mods-10"), ("整合包", "modpack"), ("A--B!", "a-b")],
)
def test_slugify(name, slug):
    assert slugify(name) == slug
