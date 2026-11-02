import json

import pytest

import modsmith as ms

USER_AGENT = "modsmith-tests/0.1"
PROJECT = "fabulously-optimized"
MINECRAFT = "1.21.1"
LARGE_PROJECT = "sodium"
PAGE_SIZE = 100


@pytest.fixture
def modrinth():
    with ms.platforms.Modrinth(USER_AGENT) as platform:
        yield platform


def test_search_filters_results(modrinth):
    results = modrinth.search("optimized", game_version=MINECRAFT, limit=3)
    assert results.total > 0
    assert all(item.project_type == "modpack" for item in results.projects)


def test_search_by_project_type_and_loader(modrinth):
    results = modrinth.search("sodium", project_type="mod", loader="fabric", limit=3)
    assert all(item.project_type == "mod" for item in results.projects)


def test_lookup_by_slug_id_and_url(modrinth):
    project = modrinth.get_project(PROJECT)
    assert modrinth.get_project(project.id).slug == PROJECT
    assert modrinth.get_project(project.url).id == project.id


def test_releases_are_filtered_and_sorted(modrinth):
    project = modrinth.get_project(PROJECT)
    releases = modrinth.list_releases(
        project, game_version=MINECRAFT, release_only=True
    )
    assert releases
    assert all(MINECRAFT in item.game_versions for item in releases)
    assert all(item.release_type == "release" for item in releases)
    dates = [item.published for item in releases]
    assert dates == sorted(dates, reverse=True)
    assert releases[0].primary_file.name.endswith(".mrpack")


def test_pages_match_the_complete_list(modrinth):
    project = modrinth.get_project(LARGE_PROJECT, project_type="mod")
    url = f"{modrinth.base_url}/project/{project.id}/version"
    complete = [item["id"] for item in modrinth.session.get_json(url)]
    assert len(complete) > 2 * PAGE_SIZE
    assert [item.id for item in modrinth.iter_releases(project)] == complete


def test_iterating_reads_only_the_pages_it_needs():
    with ms.net.Session(USER_AGENT) as session:
        pages = []
        session.http.hooks["response"].append(lambda response, **_: pages.append(1))
        with ms.platforms.Modrinth(session=session) as modrinth:
            project = modrinth.get_project(LARGE_PROJECT, project_type="mod")
            pages.clear()
            assert next(modrinth.iter_releases(project)).id
            assert len(pages) == 1


def test_full_modpack_install(modrinth, tmp_path):
    game = ms.minecraft.GameDir(tmp_path / "minecraft")
    game.path.mkdir()
    (game.path / "launcher_profiles.json").write_text(
        '{"profiles": {}}', encoding="utf-8"
    )
    game_dir = tmp_path / "instance"

    project = modrinth.get_project(PROJECT)
    release = next(
        modrinth.iter_releases(project, game_version=MINECRAFT, release_only=True)
    )
    pack = modrinth.resolve(ms.packs.load(modrinth.fetch(release, tmp_path / "cache")))
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
    assert list((game_dir / "mods").glob("*.jar"))
    launcher = ms.launcher.Launcher(game)
    key = launcher.add_profile(pack.name, version_id, game_dir, memory_mb=4096)
    profiles = json.loads((game.path / "launcher_profiles.json").read_text("utf-8"))
    assert profiles["profiles"][key]["lastVersionId"] == version_id
