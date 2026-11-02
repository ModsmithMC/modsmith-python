"""Set CURSEFORGE_API_KEY to run these; they are skipped without it."""

import os

import pytest

import modsmith as ms
from modsmith.errors import NetworkError, PlatformError

pytestmark = pytest.mark.skipif(
    not os.getenv("CURSEFORGE_API_KEY"), reason="CURSEFORGE_API_KEY is not set"
)
MINECRAFT = "1.20.1"
LARGE_PACK = "all-the-mods-9"
PACK_WITH_BLOCKED_MODS = "craft-craft-smp"


@pytest.fixture
def curseforge():
    with ms.platforms.CurseForge(os.environ["CURSEFORGE_API_KEY"]) as platform:
        yield platform


def latest_pack(curseforge, slug, into):
    project = curseforge.get_project(slug)
    release = curseforge.list_releases(project, release_only=True)[0]
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

    instance = ms.instances.Instance.open(tmp_path / "game")
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
    instance = ms.instances.Instance.open(tmp_path / "game")
    changes = instance.sync(available, session=curseforge.session)
    assert changes.added
    again = instance.sync(available, session=curseforge.session)
    assert again.added == again.updated == ()
