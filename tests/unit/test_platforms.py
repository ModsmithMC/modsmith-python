import json

import pytest
import responses

from helpers import sha1, write_zip
from modsmith.errors import NetworkError, PlatformError
from modsmith.packs import load
from modsmith.platforms import CurseForge, Modrinth, Project

MR = "https://api.modrinth.com/v2"
CF = "https://cf.test"


@pytest.fixture
def modrinth(session):
    return Modrinth(session=session)


@pytest.fixture
def curseforge(session):
    return CurseForge("test-key", session=session, base_url=CF)


def version_data(version_id="v1", date="2026-01-01T00:00:00Z", version_type="release"):
    return {
        "id": version_id,
        "project_id": "abc",
        "name": f"Version {version_id}",
        "version_type": version_type,
        "date_published": date,
        "game_versions": ["1.21.1"],
        "loaders": ["fabric"],
        "files": [
            {"filename": "extra.txt", "url": "https://cdn.test/x", "primary": False},
            {
                "filename": "pack.mrpack",
                "url": "https://cdn.test/pack.mrpack",
                "hashes": {"sha1": sha1(b"pack")},
                "size": 4,
                "primary": True,
            },
        ],
    }


PROJECT = Project("modrinth", "abc", "pack", "Pack")


@responses.activate
def test_modrinth_search(modrinth):
    responses.get(
        f"{MR}/search",
        json={
            "hits": [
                {
                    "project_id": "abc",
                    "slug": "pack",
                    "title": "Pack",
                    "project_type": "modpack",
                }
            ],
            "total_hits": 9,
            "offset": 0,
        },
    )
    results = modrinth.search("pack", game_version="1.21.1", loader="fabric")
    assert results.total == 9
    assert results.projects[0].url == "https://modrinth.com/modpack/pack"
    request = responses.calls[0].request.url
    assert "project_type" in request and "versions" in request and "categories" in request


@responses.activate
def test_modrinth_get_project_from_url(modrinth):
    responses.get(f"{MR}/project/pack", json={"id": "abc", "slug": "pack", "title": "Pack"})
    assert modrinth.get_project("https://modrinth.com/modpack/pack/").id == "abc"


@responses.activate
def test_modrinth_needs_no_key_and_identifies_tool():
    responses.get(f"{MR}/project/pack", json={"id": "abc", "slug": "pack", "title": "Pack"})
    with Modrinth("my-tool/1.0") as platform:
        platform.get_project("pack")
    assert responses.calls[0].request.headers["User-Agent"] == "my-tool/1.0"


@responses.activate
def test_modrinth_releases_newest_first(modrinth):
    responses.get(
        f"{MR}/project/abc/version",
        json=[
            version_data("old", "2026-01-01T00:00:00Z"),
            version_data("new", "2026-03-01T00:00:00Z"),
            version_data("beta", "2026-04-01T00:00:00Z", "beta"),
        ],
    )
    releases = modrinth.list_releases(PROJECT, game_version="1.21.1", release_only=True)
    assert [item.id for item in releases] == ["new", "old"]
    assert "game_versions" in responses.calls[0].request.url


@responses.activate
def test_fetch_downloads_primary_file(modrinth, tmp_path):
    responses.get(f"{MR}/project/abc/version", json=[version_data()])
    responses.get("https://cdn.test/pack.mrpack", body=b"pack")
    release = modrinth.list_releases(PROJECT)[0]
    path = modrinth.fetch(release, tmp_path)
    assert path == tmp_path / "pack.mrpack"
    assert path.read_bytes() == b"pack"


def test_curseforge_requires_key():
    with pytest.raises(PlatformError):
        CurseForge("")


def file_data(file_id=10, mod_id=1, **extra):
    data = {
        "id": file_id,
        "modId": mod_id,
        "displayName": f"File {file_id}",
        "fileName": f"file-{file_id}.jar",
        "releaseType": 1,
        "fileDate": "2026-01-01T00:00:00.1234567Z",
        "downloadUrl": f"https://cdn.test/{file_id}.jar",
        "hashes": [{"algo": 2, "value": "md5value"}, {"algo": 1, "value": "sha1value"}],
        "fileLength": 123,
    }
    return {**data, **extra}


def mod_data(mod_id=1, **extra):
    data = {
        "id": mod_id,
        "name": f"Mod {mod_id}",
        "slug": f"mod-{mod_id}",
        "classId": 6,
        "allowModDistribution": True,
        "links": {"websiteUrl": f"https://www.curseforge.com/minecraft/mc-mods/mod-{mod_id}"},
    }
    return {**data, **extra}


@responses.activate
def test_curseforge_sends_key_and_tolerates_nulls(curseforge):
    responses.get(f"{CF}/v1/mods/1", json={"data": mod_data(logo=None, links=None)})
    project = curseforge.get_project(1)
    assert project.slug == "mod-1"
    assert project.icon_url is None
    assert responses.calls[0].request.headers["x-api-key"] == "test-key"


@responses.activate
def test_unauthorized_key_is_not_retried(curseforge):
    responses.get(f"{CF}/v1/mods/1", status=403)
    with pytest.raises(NetworkError):
        curseforge.get_project(1)
    assert len(responses.calls) == 1


@responses.activate
def test_curseforge_project_from_slug(curseforge):
    responses.get(f"{CF}/v1/mods/search", json={"data": [mod_data(slug="atm")]})
    assert curseforge.get_project("https://www.curseforge.com/minecraft/modpacks/atm/").slug == "atm"
    assert "classId=4471" in responses.calls[0].request.url


@responses.activate
def test_curseforge_unknown_slug(curseforge):
    responses.get(f"{CF}/v1/mods/search", json={"data": []})
    with pytest.raises(PlatformError):
        curseforge.get_project("missing")


@responses.activate
def test_curseforge_search_filters_by_type(curseforge):
    responses.get(
        f"{CF}/v1/mods/search",
        json={"data": [mod_data()], "pagination": {"totalCount": 42}},
    )
    results = curseforge.search("create", project_type="mod", loader="neoforge")
    assert results.total == 42
    url = responses.calls[0].request.url
    assert "classId=6" in url and "modLoaderType=6" in url


@responses.activate
def test_curseforge_releases_skip_server_packs(curseforge):
    responses.get(
        f"{CF}/v1/mods/7/files",
        json={
            "data": [
                file_data(1, 7, fileDate="2026-01-01T00:00:00Z"),
                file_data(2, 7, fileDate="2026-02-01T00:00:00Z"),
                file_data(3, 7, fileDate="2026-03-01T00:00:00Z", isServerPack=True),
                file_data(4, 7, fileDate="2026-04-01T00:00:00Z", releaseType=2),
            ]
        },
    )
    project = Project("curseforge", "7", "p", "P")
    assert [r.id for r in curseforge.list_releases(project, release_only=True)] == ["2", "1"]


def manifest_pack(tmp_path, *pairs):
    manifest = {
        "manifestType": "minecraftModpack",
        "minecraft": {"version": "1.21.1", "modLoaders": [{"id": "forge-1", "primary": True}]},
        "files": [{"projectID": p, "fileID": f} for p, f in pairs],
    }
    return load(write_zip(tmp_path / "p.zip", {"manifest.json": json.dumps(manifest)}))


def stub_resolution(files, mods):
    responses.post(f"{CF}/v1/mods/files", json={"data": files})
    responses.post(f"{CF}/v1/mods", json={"data": mods})


@responses.activate
def test_resolve_fills_entries_and_maps_folders(curseforge, tmp_path):
    stub_resolution(
        [file_data(10, 1), file_data(20, 2)],
        [mod_data(1), mod_data(2, classId=12)],
    )
    pack = curseforge.resolve(manifest_pack(tmp_path, (1, 10), (2, 20)))
    assert pack.unresolved == ()
    assert [entry.path for entry in pack.entries] == [
        "mods/file-10.jar",
        "resourcepacks/file-20.jar",
    ]
    assert pack.entries[0].hashes["sha1"] == "sha1value"


@responses.activate
def test_distribution_opt_out_stays_unresolved(curseforge, tmp_path):
    stub_resolution([file_data(10, 1)], [mod_data(1, allowModDistribution=False)])
    pack = curseforge.resolve(manifest_pack(tmp_path, (1, 10)))
    entry = pack.unresolved[0]
    assert entry.path == "mods/file-10.jar"
    assert entry.urls == ()
    assert entry.manual_url == "https://www.curseforge.com/minecraft/mc-mods/mod-1/files/10"


@responses.activate
def test_missing_download_url_is_never_rebuilt(curseforge, tmp_path):
    stub_resolution([file_data(10, 1, downloadUrl=None)], [mod_data(1)])
    entry = curseforge.resolve(manifest_pack(tmp_path, (1, 10))).unresolved[0]
    assert entry.urls == ()
    assert entry.manual_url


@responses.activate
def test_unlisted_file_stays_unresolved(curseforge, tmp_path):
    stub_resolution([], [])
    pack = curseforge.resolve(manifest_pack(tmp_path, (1, 10)))
    assert len(pack.unresolved) == 1


@responses.activate
def test_requests_are_batched(curseforge):
    responses.post(f"{CF}/v1/mods/files", json={"data": []})
    curseforge._files(list(range(1, 503)))
    sizes = [len(json.loads(c.request.body)["fileIds"]) for c in responses.calls]
    assert sizes == [500, 2]
