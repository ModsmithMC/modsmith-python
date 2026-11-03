"""Set CURSEFORGE_API_KEY to run these; they are skipped without it."""

import os
import re
from itertools import islice

import pytest

import modsmith as ms
from modsmith.errors import NetworkError, PlatformError

pytestmark = pytest.mark.skipif(
    not os.getenv("CURSEFORGE_API_KEY"), reason="CURSEFORGE_API_KEY is not set"
)
MINECRAFT = "1.20.1"
LARGE_PACK = "all-the-mods-9"
PACK_WITH_BLOCKED_MODS = "craft-craft-smp"
PAGE_SIZE = 50
JEI = 238222
DEPENDENT_PROJECT = "sophisticated-backpacks"
SMALL_MOD = "appleskin"


@pytest.fixture
def curseforge():
    with ms.platforms.CurseForge(os.environ["CURSEFORGE_API_KEY"]) as platform:
        yield platform


def latest_pack(curseforge, slug, into):
    project = curseforge.get_project(slug)
    release = next(curseforge.iter_releases(project, release_only=True))
    return ms.packs.load(curseforge.fetch(release, into))


def test_invalid_key_is_rejected_without_retry():
    with (
        ms.platforms.CurseForge("invalid-key") as platform,
        pytest.raises(NetworkError) as error,
    ):
        platform.get_project(1)
    assert error.value.status in (401, 403)


def test_search_and_lookup(curseforge):
    results = curseforge.search("create", game_version=MINECRAFT, limit=5)
    assert results.total > 0
    project = results.projects[0]
    assert curseforge.get_project(project.id).slug == project.slug
    assert curseforge.get_project(project.slug).id == project.id


def test_unknown_slug(curseforge):
    with pytest.raises(PlatformError):
        curseforge.get_project("modsmith-no-such-project")


def test_search_mods_by_loader(curseforge):
    results = curseforge.search("jei", project_type="mod", loader="forge", limit=5)
    assert results.projects


def test_releases_span_every_page(curseforge):
    project = curseforge.get_project(JEI, project_type="mod")
    releases = curseforge.list_releases(project, game_version=MINECRAFT)
    assert len(releases) > PAGE_SIZE
    assert len({item.id for item in releases}) == len(releases)


def test_iterating_reads_only_the_pages_it_needs():
    with ms.net.Session() as session:
        pages = []
        session.http.hooks["response"].append(lambda response, **_: pages.append(1))
        key = os.environ["CURSEFORGE_API_KEY"]
        with ms.platforms.CurseForge(key, session=session) as curseforge:
            project = curseforge.get_project(JEI, project_type="mod")
            pages.clear()
            releases = curseforge.iter_releases(project)
            assert next(releases).id
            assert len(pages) == 1
            assert len(list(islice(releases, PAGE_SIZE + 1))) == PAGE_SIZE + 1
            assert len(pages) == 2


def test_first_release_is_the_newest(curseforge):
    project = curseforge.get_project(JEI, project_type="mod")
    first = list(islice(curseforge.iter_releases(project), 3 * PAGE_SIZE))
    dates = [item.published for item in first]
    assert dates == sorted(dates, reverse=True)


def test_releases_exclude_server_packs(curseforge):
    project = curseforge.get_project(LARGE_PACK)
    releases = curseforge.list_releases(project, release_only=True)
    assert releases
    assert all(item.release_type == "release" for item in releases)
    dates = [item.published for item in releases]
    assert dates == sorted(dates, reverse=True)
    assert all("server" not in item.primary_file.name.lower() for item in releases[:5])


def test_resolve_large_real_pack(curseforge, tmp_path):
    pack = latest_pack(curseforge, LARGE_PACK, tmp_path)
    assert pack.format == "curseforge"
    assert pack.unresolved

    resolved = curseforge.resolve(pack)
    required = [entry for entry in resolved.entries if entry.wanted("client")]
    assert len(resolved.entries) == len(pack.entries)
    assert required
    assert all(entry.path and entry.hashes for entry in required)


def test_distribution_opt_out_needs_a_manual_download(curseforge, tmp_path):
    resolved = curseforge.resolve(
        latest_pack(curseforge, PACK_WITH_BLOCKED_MODS, tmp_path)
    )
    blocked = [entry for entry in resolved.unresolved if entry.wanted("client")]
    assert blocked, "pick another pack: this one no longer has blocked mods"
    for entry in blocked:
        assert entry.path
        assert entry.urls == ()
        assert entry.manual_url.startswith("https://www.curseforge.com/")

    instance = ms.instances.Instance(tmp_path / "game")
    with pytest.raises(ms.errors.UnresolvedEntriesError):
        instance.sync(resolved, session=curseforge.session)
    assert not instance.path.exists()


def test_install_resolved_files(curseforge, tmp_path):
    resolved = curseforge.resolve(
        latest_pack(curseforge, PACK_WITH_BLOCKED_MODS, tmp_path)
    )
    available = resolved.with_entries(
        tuple(entry for entry in resolved.entries if entry.is_resolved)
    )
    instance = ms.instances.Instance(tmp_path / "game")
    changes = instance.sync(available, session=curseforge.session)
    assert changes.added
    again = instance.sync(available, session=curseforge.session)
    assert again.added == again.updated == ()


def dependent_release(curseforge):
    project = curseforge.get_project(DEPENDENT_PROJECT, project_type="mod")
    releases = curseforge.iter_releases(project, game_version=MINECRAFT, loader="forge")
    return next(
        item
        for item in releases
        if any(dependency.kind == "required" for dependency in item.dependencies)
    )


def test_get_release_matches_the_listing(curseforge):
    release = dependent_release(curseforge)
    assert curseforge.get_release(release.id) == release


def test_unknown_release_is_a_platform_error(curseforge):
    with pytest.raises(PlatformError):
        curseforge.get_release("1")


def test_resolve_finds_real_dependencies(curseforge):
    release = dependent_release(curseforge)
    result = ms.platforms.resolve_dependencies(
        curseforge,
        [release],
        game_version=MINECRAFT,
        loader="forge",
        release_only=False,
    )
    assert result.releases[-1] == release
    assert len(result.releases) > 1
    assert not result.missing


def test_identify_matches_the_real_fingerprint(curseforge, tmp_path):
    project = curseforge.get_project(SMALL_MOD, project_type="mod")
    release = next(
        curseforge.iter_releases(project, game_version=MINECRAFT, loader="forge")
    )
    path = curseforge.fetch(release, tmp_path)
    unknown = tmp_path / "unknown.jar"
    unknown.write_bytes(b"not a real mod")

    found = curseforge.identify([path, unknown])

    assert list(found) == [path]
    assert found[path].id == release.id


def test_projects_report_their_real_type(curseforge):
    project = curseforge.search("", project_type="resourcepack", limit=1).projects[0]
    assert project.project_type == "resourcepack"
    found = curseforge.get_project(project.id, project_type="mod")
    assert found.project_type == "resourcepack"


def test_add_a_mod_with_its_dependencies(curseforge, tmp_path):
    instance = ms.instances.Instance.create(
        tmp_path / "game", minecraft=MINECRAFT, loader="forge"
    )
    release = dependent_release(curseforge)

    plan = instance.plan(curseforge, [release], release_only=False)
    assert plan.ok
    assert len(plan.additions) > 1
    instance.add(plan)

    for item in instance.additions:
        assert (instance.path / item.path).is_file()
    instance.remove(release.project_id)
    assert instance.additions == ()


def test_search_puts_the_best_match_first(curseforge):
    results = curseforge.search("jei", project_type="mod", limit=3)
    assert results.projects[0].id == str(JEI)


def test_releases_separate_game_versions_from_loaders(curseforge):
    project = curseforge.get_project(SMALL_MOD, project_type="mod")
    release = next(curseforge.iter_releases(project, loader="fabric"))
    assert release.loaders
    assert set(release.loaders) <= {"forge", "neoforge", "fabric", "quilt"}
    assert all(version[0].isdigit() for version in release.game_versions)


def test_a_slug_is_found_whatever_kind_was_asked_for(curseforge):
    project = curseforge.get_project("faithful-32x", project_type="mod")
    assert project.project_type == "resourcepack"


def test_search_sorts_and_reads_past_one_page(curseforge):
    results = curseforge.search("", project_type="mod", sort="downloads", limit=60)
    assert len(results.projects) == 60
    # CurseForge sorts by a cached count, so neighbours can be slightly out of order.
    counts = [item.downloads for item in results.projects]
    assert counts[0] == max(counts)
    assert sum(counts[:10]) > sum(counts[-10:])


def test_search_results_describe_projects(curseforge):
    project = curseforge.search("jei", project_type="mod", limit=1).projects[0]
    assert project.author == "mezz"
    assert project.updated
    assert project.follows
    assert project.categories
    assert "1.20.1" in project.game_versions


def test_bulk_lookup(curseforge):
    found = curseforge.get_projects([str(JEI), "238223000", "not-a-number"])
    assert set(found) == {str(JEI)}
    assert found[str(JEI)].slug == "jei"


def test_changelogs_are_plain_text(curseforge):
    project = curseforge.get_project(JEI, project_type="mod")
    release = next(curseforge.iter_releases(project))
    assert release.version is None
    text = curseforge.changelog(release)
    assert text
    # Text may hold angle brackets, as in an email address, but no tags.
    assert not re.search(r"</?(a|br|div|h[1-6]|li|p|ul)", text)


def test_authors_are_all_listed(curseforge):
    project = curseforge.get_project("jei", project_type="mod")
    authors = curseforge.authors(project)
    assert authors[0] == project.author == "mezz"
