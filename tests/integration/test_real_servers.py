"""Runs against real servers: uv run pytest tests/integration -o addopts="" -m network"""

import json

import pytest

import modsmith as ms

pytestmark = pytest.mark.network
USER_AGENT = "modsmith-tests/0.1"
PROJECT = "fabulously-optimized"
MINECRAFT = "1.21.1"


def assert_libraries_present(game, version_id):
    for item in game.version(version_id).raw.get("libraries", []):
        artifact = (item.get("downloads") or {}).get("artifact") or {}
        path = artifact.get("path") or ms.minecraft.maven_path(item["name"])
        assert (game.libraries_dir / path).is_file(), path


def test_modrinth_catalogue():
    with ms.platforms.Modrinth(USER_AGENT) as modrinth:
        results = modrinth.search("optimized", game_version=MINECRAFT, limit=3)
        assert results.projects
        project = modrinth.get_project(PROJECT)
        releases = modrinth.list_releases(project, game_version=MINECRAFT)
        assert releases[0].primary_file.name.endswith(".mrpack")


def test_install_real_fabric_modpack_end_to_end(tmp_path):
    game = ms.minecraft.GameDir(tmp_path / "minecraft")
    game.path.mkdir()
    (game.path / "launcher_profiles.json").write_text('{"profiles": {}}', encoding="utf-8")
    game_dir = tmp_path / "instance"

    with ms.platforms.Modrinth(USER_AGENT) as modrinth:
        project = modrinth.get_project(PROJECT)
        release = modrinth.list_releases(
            project, game_version=MINECRAFT, release_only=True
        )[0]
        pack = ms.packs.load(modrinth.fetch(release, tmp_path / "cache"))
        pack = modrinth.resolve(pack)
        assert pack.unresolved == ()

        version_id = pack.loader.install(
            game, cache_dir=tmp_path / "cache", session=modrinth.session
        )
        instance = ms.instances.Instance.open(game_dir)
        preview = instance.diff(pack)
        assert preview.added
        changes = instance.sync(pack, session=modrinth.session)
        assert sorted(changes.added) == sorted(preview.added)

        again = instance.sync(pack, session=modrinth.session)
        assert again.added == again.updated == ()

    assert game.client_jar(MINECRAFT).is_file()
    assert_libraries_present(game, version_id)
    jars = list((game_dir / "mods").glob("*.jar"))
    assert jars

    launcher = ms.launcher.Launcher(game)
    key = launcher.add_profile(pack.name, version_id, game_dir, memory_mb=4096)
    profiles = json.loads((game.path / "launcher_profiles.json").read_text("utf-8"))
    assert profiles["profiles"][key]["lastVersionId"] == version_id


@pytest.mark.parametrize(
    "loader",
    [
        ms.loaders.Fabric("0.16.10", MINECRAFT),
        ms.loaders.Quilt("0.30.2", MINECRAFT),
    ],
    ids=lambda item: item.kind,
)
def test_install_meta_loaders(tmp_path, loader):
    game = ms.minecraft.GameDir(tmp_path)
    version_id = loader.install(game)
    assert game.has_version(version_id)
    assert_libraries_present(game, version_id)


@pytest.mark.parametrize(
    ("loader", "version_id"),
    [
        (ms.loaders.Forge("36.2.42", "1.16.5"), "1.16.5-forge-36.2.42"),
        (ms.loaders.NeoForge("47.1.106", "1.20.1"), "1.20.1-forge-47.1.106"),
        (ms.loaders.NeoForge("21.1.233", MINECRAFT), "neoforge-21.1.233"),
    ],
    ids=["forge-1.16.5", "neoforge-1.20.1", "neoforge-21.1"],
)
def test_processor_loader_files_without_running_processors(tmp_path, loader, version_id):
    game = ms.minecraft.GameDir(tmp_path / "minecraft")
    with ms.net.Session() as session:
        installer = loader.fetch_installer(session=session, cache_dir=tmp_path / "cache")
        assert installer.version_id == version_id
        installer.extract_bundled_libraries(game.libraries_dir)
        resources = [loader._resource(item, game) for item in installer.libraries]
        ms.net.download([item for item in resources if item], session=session)

    game.write_version(version_id, installer.version_json)
    assert_libraries_present(game, version_id)
