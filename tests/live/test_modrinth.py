import json

import pytest

import modsmith as ms
from modsmith.errors import NetworkError

USER_AGENT = "modsmith-tests/0.1"
PROJECT = "fabulously-optimized"
MINECRAFT = "1.21.1"
LARGE_PROJECT = "sodium"
DEPENDENT_PROJECT = "iris"
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
    instance = ms.instances.Instance(game_dir)
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


def with_required_dependency(modrinth, slug):
    project = modrinth.get_project(slug)
    releases = modrinth.iter_releases(project, game_version=MINECRAFT, loader="fabric")
    return next(
        item
        for item in releases
        if any(dependency.kind == "required" for dependency in item.dependencies)
    )


def test_releases_list_dependencies(modrinth):
    release = with_required_dependency(modrinth, DEPENDENT_PROJECT)
    assert all(
        dependency.project_id or dependency.release_id
        for dependency in release.dependencies
    )


def test_get_release_matches_the_listing(modrinth):
    release = with_required_dependency(modrinth, DEPENDENT_PROJECT)
    assert modrinth.get_release(release.id) == release


def test_unknown_release_is_a_network_error(modrinth):
    with pytest.raises(NetworkError) as error:
        modrinth.get_release("0000000000000000")
    assert error.value.status == 404


def test_resolve_finds_real_dependencies(modrinth):
    release = with_required_dependency(modrinth, DEPENDENT_PROJECT)
    result = ms.platforms.resolve_dependencies(
        modrinth,
        [release],
        game_version=MINECRAFT,
        loader="fabric",
        release_only=False,
    )
    assert result.releases[-1] == release
    assert len(result.releases) > 1
    assert not result.missing


def test_identify_finds_a_downloaded_file(modrinth, tmp_path):
    project = modrinth.get_project(LARGE_PROJECT)
    release = next(
        modrinth.iter_releases(project, game_version=MINECRAFT, loader="fabric")
    )
    path = modrinth.fetch(release, tmp_path)
    copy = tmp_path / "copy.jar"
    copy.write_bytes(path.read_bytes())
    unknown = tmp_path / "unknown.jar"
    unknown.write_bytes(b"not a real mod")
    updates = []

    found = modrinth.identify([path, copy, unknown], progress=updates.append)

    assert sorted(item.name for item in found) == sorted([path.name, copy.name])
    assert {item.id for item in found.values()} == {release.id}
    assert updates[-1].current == updates[-1].total == 3


def test_identify_with_nothing_makes_no_request(modrinth):
    assert modrinth.identify([]) == {}


def fabric_instance(tmp_path):
    return ms.instances.Instance.create(
        tmp_path / "game", minecraft=MINECRAFT, loader="fabric"
    )


def test_add_and_remove_a_mod_with_its_dependencies(modrinth, tmp_path):
    instance = fabric_instance(tmp_path)
    release = with_required_dependency(modrinth, DEPENDENT_PROJECT)

    plan = instance.plan(modrinth, [release], release_only=False)
    assert plan.ok
    assert len(plan.additions) > 1
    instance.add(plan)

    for item in instance.additions:
        assert (instance.path / item.path).is_file()
        assert item.path.startswith("mods/")
        assert item.name
    assert [item.release_id for item in instance.additions if item.requested] == [
        release.id
    ]
    instance.remove(DEPENDENT_PROJECT)
    assert instance.additions == ()
    assert not any((instance.path / "mods").iterdir())


@pytest.mark.parametrize(
    ("kind", "folder"),
    [("resourcepack", "resourcepacks"), ("shader", "shaderpacks")],
)
def test_packs_are_planned_into_their_folders(modrinth, tmp_path, kind, folder):
    project = modrinth.search(
        "", project_type=kind, game_version=MINECRAFT, limit=1
    ).projects[0]
    plan = fabric_instance(tmp_path).plan(modrinth, [project], project_type=kind)
    assert plan.additions[0].path.startswith(f"{folder}/")
    assert plan.additions[0].project_type == kind


def test_adopt_recognises_a_downloaded_mod(modrinth, tmp_path):
    instance = fabric_instance(tmp_path)
    project = modrinth.get_project(LARGE_PROJECT)
    release = next(
        modrinth.iter_releases(project, game_version=MINECRAFT, loader="fabric")
    )
    path = modrinth.fetch(release, instance.path / "mods")

    adopted = instance.adopt(modrinth)

    assert [item.release_id for item in adopted] == [release.id]
    assert adopted[0].path == f"mods/{path.name}"
    assert adopted[0].slug == LARGE_PROJECT


def test_mrpack_entries_name_their_modrinth_release(modrinth, tmp_path):
    project = modrinth.get_project(PROJECT)
    release = next(modrinth.iter_releases(project, release_only=True))
    pack = ms.packs.load(modrinth.fetch(release, tmp_path))
    refs = [entry.ref for entry in pack.entries if entry.ref]
    assert len(refs) == len(pack.entries)
    found = modrinth.get_release(refs[0].file_id)
    assert found.project_id == refs[0].project_id


def test_search_sorts_and_reads_past_one_page(modrinth):
    results = modrinth.search("", project_type="mod", sort="downloads", limit=150)
    assert len(results.projects) == 150
    counts = [item.downloads for item in results.projects]
    assert counts == sorted(counts, reverse=True)
    assert len({item.id for item in results.projects}) == 150


def test_search_results_describe_projects(modrinth):
    project = modrinth.search(LARGE_PROJECT, project_type="mod", limit=1).projects[0]
    assert project.author
    assert project.updated
    assert project.follows
    assert project.categories
    assert not {"Fabric", "Quilt", "Neoforge"} & set(project.categories)
    assert all(
        version[0].isdigit() and "-" not in version for version in project.game_versions
    )


def test_bulk_lookup(modrinth):
    found = modrinth.get_projects(
        [LARGE_PROJECT, DEPENDENT_PROJECT, "no-such-project-x"]
    )
    assert set(found) == {LARGE_PROJECT, DEPENDENT_PROJECT}
    assert found[LARGE_PROJECT].game_versions
