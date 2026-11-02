"""Runs against the real CurseForge API.

Set CURSEFORGE_API_KEY first, then:
    uv run pytest tests/integration/test_curseforge.py -o addopts="" -m network
"""

import os

import pytest

import modsmith as ms

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        not os.getenv("CURSEFORGE_API_KEY"), reason="CURSEFORGE_API_KEY is not set"
    ),
]
MINECRAFT = "1.20.1"


@pytest.fixture
def curseforge():
    with ms.platforms.CurseForge(os.environ["CURSEFORGE_API_KEY"]) as platform:
        yield platform


def test_search_and_lookup(curseforge):
    results = curseforge.search("create", game_version=MINECRAFT, limit=5)
    assert results.total > 0
    project = results.projects[0]
    assert curseforge.get_project(project.id).slug == project.slug
    assert curseforge.get_project(project.slug).id == project.id


def test_search_mods_by_loader(curseforge):
    results = curseforge.search("jei", project_type="mod", loader="forge", limit=5)
    assert results.projects


def test_releases_exclude_server_packs(curseforge):
    project = curseforge.get_project("all-the-mods-9")
    releases = curseforge.list_releases(project, release_only=True)
    assert releases
    assert all(item.release_type == "release" for item in releases)
    assert releases == sorted(releases, key=lambda r: r.published, reverse=True)
    assert all("server" not in item.primary_file.name.lower() for item in releases[:5])


def test_resolve_real_pack(curseforge, tmp_path):
    project = curseforge.get_project("all-the-mods-9")
    release = curseforge.list_releases(project, release_only=True)[0]
    pack = ms.packs.load(curseforge.fetch(release, tmp_path))
    assert pack.format == "curseforge"
    assert pack.unresolved

    resolved = curseforge.resolve(pack)
    assert len(resolved.entries) == len(pack.entries)
    required = [entry for entry in resolved.entries if entry.wanted("client")]
    assert required
    assert all(entry.path and entry.hashes for entry in required)
    assert sum(entry.is_resolved for entry in required) > len(required) / 2
    for entry in resolved.unresolved:
        assert entry.manual_url
