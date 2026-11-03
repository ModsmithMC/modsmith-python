import threading

import pytest

import modsmith as ms
from modsmith.errors import Cancelled, UnsupportedError
from modsmith.packs import FileRef
from modsmith.platforms import Project, resolve_dependencies
from tests.lib.catalog import Catalog, on, release


def resolve(platform, *releases, **options):
    options.setdefault("game_version", "1.21.1")
    options.setdefault("loader", "fabric")
    return resolve_dependencies(platform, releases, **options)


def ids(resolution):
    return [item.id for item in resolution.releases]


def test_release_without_dependencies_resolves_to_itself():
    mod = release("a")
    assert ids(resolve(Catalog(mod), mod)) == ["a-1"]


def test_dependencies_come_before_what_needs_them():
    a, b, c = release("a", "1", on("b")), release("b", "1", on("c")), release("c")
    result = resolve(Catalog(a, b, c), a)
    assert ids(result) == ["c-1", "b-1", "a-1"]
    assert not result.conflicts
    assert not result.missing


def test_newest_compatible_release_is_chosen():
    a = release("a", "1", on("b"))
    catalog = Catalog(
        a,
        release("b", "3", game="1.20.1"),
        release("b", "2", loader="forge"),
        release("b", "1"),
    )
    assert ids(resolve(catalog, a)) == ["b-1", "a-1"]


def test_exact_release_wins_over_newest():
    a = release("a", "1", on("b", exact="b-1"))
    assert ids(resolve(Catalog(a, release("b", "2"), release("b", "1")), a)) == [
        "b-1",
        "a-1",
    ]


def test_exact_release_can_name_no_project():
    a = release("a", "1", on(None, exact="b-1"))
    assert ids(resolve(Catalog(a, release("b")), a)) == ["b-1", "a-1"]


def test_shared_dependency_is_listed_once():
    a, b, c = release("a", "1", on("c")), release("b", "1", on("c")), release("c")
    assert ids(resolve(Catalog(a, b, c), a, b)) == ["c-1", "a-1", "b-1"]


def test_requested_release_meets_a_dependency_and_keeps_the_order():
    a, b = release("a", "1", on("b")), release("b", "1")
    assert ids(resolve(Catalog(a, release("b", "2"), b), a, b)) == ["b-1", "a-1"]


def test_dependency_cycle_ends():
    a, b = release("a", "1", on("b")), release("b", "1", on("a"))
    assert ids(resolve(Catalog(a, b), a)) == ["b-1", "a-1"]


def test_two_exact_versions_are_a_conflict():
    a = release("a", "1", on("c", exact="c-1"))
    b = release("b", "1", on("c", exact="c-2"))
    result = resolve(Catalog(a, b, release("c", "1"), release("c", "2")), a, b)
    assert ids(result) == ["c-1", "a-1", "b-1"]
    [conflict] = result.conflicts
    assert conflict.release == b
    assert conflict.chosen.id == "c-1"
    assert conflict.dependency.release_id == "c-2"


def test_incompatible_release_is_a_conflict():
    a = release("a", "1", on("b", "incompatible"))
    b = release("b")
    [conflict] = resolve(Catalog(a, b), a, b).conflicts
    assert conflict.release == a
    assert conflict.chosen == b


def test_incompatible_exact_release_only_matches_that_release():
    a = release("a", "1", on("b", "incompatible", "b-1"))
    b = release("b", "2")
    assert not resolve(Catalog(a, b), a, b).conflicts


def test_incompatible_project_that_is_absent_is_fine():
    a = release("a", "1", on("b", "incompatible"))
    assert not resolve(Catalog(a), a).conflicts


def test_incompatible_with_an_installed_release():
    a = release("a")
    installed = release("b", "1", on("a", "incompatible"))
    [conflict] = resolve(Catalog(a, installed), a, installed=[installed]).conflicts
    assert conflict.release == installed
    assert conflict.chosen == a


def test_missing_project_is_reported():
    a = release("a", "1", on("gone"))
    result = resolve(Catalog(a), a)
    assert ids(result) == ["a-1"]
    [missing] = result.missing
    assert missing.release == a
    assert missing.dependency.project_id == "gone"


def test_project_with_no_compatible_release_is_reported():
    a = release("a", "1", on("b"))
    assert len(resolve(Catalog(a, release("b", game="1.20.1")), a).missing) == 1


def test_missing_exact_release_is_reported():
    a = release("a", "1", on("b", exact="b-9"))
    assert len(resolve(Catalog(a, release("b")), a).missing) == 1


def test_embedded_dependencies_are_not_installed():
    a = release("a", "1", on("b", "embedded"))
    assert ids(resolve(Catalog(a, release("b")), a)) == ["a-1"]


def test_optional_dependencies_are_opt_in():
    a = release("a", "1", on("b", "optional"))
    catalog = Catalog(a, release("b"))
    assert ids(resolve(catalog, a)) == ["a-1"]
    assert ids(resolve(catalog, a, include_optional=True)) == ["b-1", "a-1"]


def test_pre_releases_are_left_out_unless_allowed():
    a = release("a", "1", on("b"))
    catalog = Catalog(a, release("b", release_type="beta"))
    assert len(resolve(catalog, a).missing) == 1
    assert ids(resolve(catalog, a, release_only=False)) == ["b-1", "a-1"]


def test_installed_release_meets_a_dependency():
    a = release("a", "1", on("b"))
    installed = release("b", "1")
    catalog = Catalog(a, release("b", "2"), installed)
    assert ids(resolve(catalog, a, installed=[installed])) == ["a-1"]


def test_installed_release_with_the_wrong_version_is_a_conflict():
    a = release("a", "1", on("b", exact="b-2"))
    installed = release("b", "1")
    result = resolve(Catalog(a, release("b", "2"), installed), a, installed=[installed])
    assert ids(result) == ["a-1"]
    assert result.conflicts[0].chosen == installed


def test_requested_release_replaces_an_installed_one():
    new, old = release("a", "2"), release("a", "1")
    assert ids(resolve(Catalog(new, old), new, installed=[old])) == ["a-2"]


def test_quilt_falls_back_to_fabric():
    a = release("a", "1", on("b"), loader="quilt")
    catalog = Catalog(a, release("b", "2"), release("b", "1", loader="quilt"))
    assert ids(resolve(catalog, a, loader="quilt")) == ["b-1", "a-1"]

    catalog = Catalog(a, release("b", "2"))
    assert ids(resolve(catalog, a, loader="quilt")) == ["b-2", "a-1"]
    assert len(resolve(catalog, a, loader="forge").missing) == 1


def test_cancel_stops_the_search():
    token = ms.CancelToken()
    token.cancel()
    a = release("a", "1", on("b"))
    with pytest.raises(Cancelled):
        resolve(Catalog(a, release("b")), a, cancel=token)


def test_default_platform_cannot_look_up_releases():
    class NoLookup(Catalog):
        get_release = ms.platforms.Platform.get_release

    a = release("a", "1", on("b", exact="b-1"))
    with pytest.raises(UnsupportedError):
        resolve(NoLookup(a, release("b")), a)


def test_default_identify_knows_nothing(tmp_path):
    class NoIdentify(Catalog):
        identify = ms.platforms.Platform.identify

    assert NoIdentify().identify([tmp_path / "unread.jar"]) == {}


def test_resolving_is_safe_from_several_threads():
    a = release("a", "1", on("b"))
    catalog = Catalog(a, release("b"))
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(ids(resolve(catalog, a))))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [["b-1", "a-1"]] * 8


def test_file_reference_meets_a_dependency():
    a = release("a", "1", on("b"))
    catalog = Catalog(a, release("b", "2"), release("b", "1"))
    installed = [FileRef("catalog", "b", "b-1")]
    assert ids(resolve(catalog, a, installed=installed)) == ["a-1"]


def test_file_reference_with_the_wrong_version_reports_its_release():
    a = release("a", "1", on("b", exact="b-2"))
    old = release("b", "1")
    installed = [FileRef("catalog", "b", "b-1")]
    result = resolve(Catalog(a, release("b", "2"), old), a, installed=installed)
    assert ids(result) == ["a-1"]
    assert result.conflicts[0].chosen == old


def test_unknown_file_reference_is_still_reported():
    a = release("a", "1", on("b", exact="b-2"))
    installed = [FileRef("catalog", "b", "gone")]
    result = resolve(Catalog(a, release("b", "2")), a, installed=installed)
    assert result.conflicts[0].chosen.id == "gone"


def test_incompatible_with_an_installed_file_reference():
    a = release("a", "1", on("b", kind="incompatible"))
    installed = [FileRef("catalog", "b", "b-1")]
    result = resolve(Catalog(a, release("b")), a, installed=installed)
    assert [item.chosen.id for item in result.conflicts] == ["b-1"]


def test_file_references_from_other_platforms_are_ignored():
    a = release("a", "1", on("b"))
    installed = [FileRef("elsewhere", "b", "b-1")]
    assert ids(resolve(Catalog(a, release("b")), a, installed=installed)) == [
        "b-1",
        "a-1",
    ]


def test_latest_release_with_any_loader():
    catalog = Catalog(release("p", "2", loader="iris"), release("p", "1"))
    project = Project("catalog", "p", "p", "P")
    assert catalog.latest_release(project).id == "p-2"
    assert catalog.latest_release(project, loader="fabric").id == "p-1"
    assert catalog.latest_release(project, loader="forge") is None


def test_latest_release_falls_back_from_quilt_to_fabric():
    catalog = Catalog(release("p", "2"), release("p", "1", loader="quilt"))
    project = Project("catalog", "p", "p", "P")
    assert catalog.latest_release(project, loader="quilt").id == "p-1"
    assert (
        Catalog(release("p", "2")).latest_release(project, loader="quilt").id == "p-2"
    )


def test_latest_release_filters_game_version_and_pre_releases():
    catalog = Catalog(
        release("p", "3", release_type="beta"),
        release("p", "2", game="1.20.1"),
        release("p", "1"),
    )
    project = Project("catalog", "p", "p", "P")
    assert catalog.latest_release(project).id == "p-3"
    assert catalog.latest_release(project, release_only=True).id == "p-2"
    assert catalog.latest_release(project, game_version="1.21.1").id == "p-3"
    found = catalog.latest_release(project, game_version="1.21.1", release_only=True)
    assert found.id == "p-1"


@pytest.mark.parametrize(
    ("kind", "folder"),
    [
        ("mod", "mods"),
        ("resourcepack", "resourcepacks"),
        ("shader", "shaderpacks"),
        ("modpack", None),
        ("datapack", None),
    ],
)
def test_project_folders(kind, folder):
    assert Project("x", "1", "a", "A", project_type=kind).folder == folder
