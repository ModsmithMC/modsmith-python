import json

import pytest
import responses

from cursecraft.core.errors import ConfigError, HttpError, SourceError
from cursecraft.core.http import HttpClient
from cursecraft.sources.base import PackEntry, PackManifest, Project
from cursecraft.sources.curseforge import (
    CfFile,
    CfMod,
    CurseForgeClient,
    CurseForgeSource,
)

BASE = "https://cf.test"
KEY = "test-key"


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


@pytest.fixture
def source():
    return CurseForgeSource(CurseForgeClient(HttpClient(backoff=0), KEY, BASE))


PROJECT = Project("curseforge", 7, "pack", "Pack")


def test_cf_file_tolerates_missing_fields():
    file = CfFile.from_dict({"id": 1, "modId": 2, "fileName": "a.jar"})
    assert file.display_name == "a.jar"
    assert file.download_url is None
    assert file.hash is None
    assert not file.is_server_pack


def test_cf_file_prefers_sha1():
    file = CfFile.from_dict(file_data())
    assert (file.hash, file.algo) == ("sha1value", "sha1")


def test_cf_file_falls_back_to_md5():
    file = CfFile.from_dict(file_data(hashes=[{"algo": 2, "value": "m"}, {"algo": 9, "value": "x"}]))
    assert (file.hash, file.algo) == ("m", "md5")


def test_cf_mod_tolerates_missing_fields():
    mod = CfMod.from_dict({"id": 1, "name": "A", "slug": "a", "logo": None, "links": None})
    assert mod.icon_url is None
    assert mod.allow_distribution is None


def test_missing_api_key_is_a_config_error():
    client = CurseForgeClient(HttpClient(), None, BASE)
    with pytest.raises(ConfigError):
        client.get_mod(1)


@responses.activate
def test_api_key_is_sent(source):
    responses.get(f"{BASE}/v1/mods/1", json={"data": mod_data()})
    assert source.get_project(1).slug == "mod-1"
    assert responses.calls[0].request.headers["x-api-key"] == KEY


@responses.activate
def test_unauthorized_key_is_not_retried(source):
    responses.get(f"{BASE}/v1/mods/1", status=403)
    with pytest.raises(HttpError):
        source.get_project(1)
    assert len(responses.calls) == 1


@pytest.mark.parametrize("ref", ["all-the-mods", "https://www.curseforge.com/minecraft/modpacks/all-the-mods/"])
@responses.activate
def test_get_project_by_slug_or_url(source, ref):
    responses.get(f"{BASE}/v1/mods/search", json={"data": [mod_data(slug="all-the-mods")]})
    assert source.get_project(ref).slug == "all-the-mods"
    assert "slug=all-the-mods" in responses.calls[0].request.url
    assert "classId=4471" in responses.calls[0].request.url


@responses.activate
def test_get_project_unknown_slug(source):
    responses.get(f"{BASE}/v1/mods/search", json={"data": []})
    with pytest.raises(SourceError):
        source.get_project("missing")


@responses.activate
def test_search_returns_projects(source):
    responses.get(
        f"{BASE}/v1/mods/search",
        json={"data": [mod_data()], "pagination": {"totalCount": 42}},
    )
    page = source.search("create")
    assert page.total == 42
    assert page.projects[0].source == "curseforge"
    assert "searchFilter=create" in responses.calls[0].request.url


def stub_files(*files):
    responses.get(f"{BASE}/v1/mods/7/files", json={"data": list(files)})


@responses.activate
def test_latest_skips_server_packs_and_prereleases(source):
    stub_files(
        file_data(1, 7, fileDate="2026-01-01T00:00:00Z"),
        file_data(2, 7, fileDate="2026-02-01T00:00:00Z"),
        file_data(3, 7, fileDate="2026-03-01T00:00:00Z", isServerPack=True),
        file_data(4, 7, fileDate="2026-04-01T00:00:00Z", releaseType=2),
    )
    assert source.latest_pack_file(PROJECT).id == 2


@responses.activate
def test_latest_allows_prerelease_on_request(source):
    stub_files(
        file_data(2, 7, fileDate="2026-02-01T00:00:00Z"),
        file_data(4, 7, fileDate="2026-04-01T00:00:00Z", releaseType=2),
    )
    assert source.latest_pack_file(PROJECT, allow_prerelease=True).id == 4


@responses.activate
def test_latest_falls_back_when_only_prereleases_exist(source):
    stub_files(file_data(4, 7, releaseType=3))
    assert source.latest_pack_file(PROJECT).id == 4


@responses.activate
def test_latest_without_client_files_fails(source):
    stub_files(file_data(3, 7, isServerPack=True))
    with pytest.raises(SourceError):
        source.latest_pack_file(PROJECT)


def manifest_data(**extra):
    data = {
        "manifestType": "minecraftModpack",
        "name": "Pack",
        "version": "1.0",
        "overrides": "custom",
        "minecraft": {
            "version": "1.21.1",
            "recommendedRam": 6144,
            "modLoaders": [
                {"id": "fabric-0.1", "primary": False},
                {"id": "neoforge-21.1.233", "primary": True},
            ],
        },
        "files": [
            {"projectID": 1, "fileID": 10, "required": True},
            {"projectID": 2, "fileID": 20, "required": False},
            {"projectID": 3, "fileID": 30},
        ],
    }
    return {**data, **extra}


def test_read_manifest_honors_primary_required_and_overrides(source):
    manifest = source.read_manifest(manifest_data())
    assert manifest.loader_id == "neoforge-21.1.233"
    assert manifest.overrides == "custom"
    assert manifest.recommended_ram == 6144
    assert manifest.entries == [PackEntry(1, 10), PackEntry(3, 30)]


def test_read_manifest_rejects_other_formats(source):
    with pytest.raises(SourceError):
        source.read_manifest({"manifestType": "other"})


def test_read_manifest_requires_loader(source):
    data = manifest_data()
    data["minecraft"]["modLoaders"] = []
    with pytest.raises(SourceError):
        source.read_manifest(data)


def manifest_for(*pairs):
    return PackManifest("Pack", "1", "1.21.1", "forge-1", entries=[PackEntry(p, f) for p, f in pairs])


def stub_resolution(files, mods):
    responses.post(f"{BASE}/v1/mods/files", json={"data": files})
    responses.post(f"{BASE}/v1/mods", json={"data": mods})


@responses.activate
def test_resolve_files_maps_folders_by_class(source):
    stub_resolution(
        [file_data(10, 1), file_data(20, 2)],
        [mod_data(1), mod_data(2, classId=12)],
    )
    files = source.resolve_files(manifest_for((1, 10), (2, 20)))
    assert [f.relative_path for f in files] == ["mods/file-10.jar", "resourcepacks/file-20.jar"]
    assert json.loads(responses.calls[1].request.body)["filterPcOnly"] is False


@responses.activate
def test_missing_file_is_detected(source):
    stub_resolution([file_data(10, 1)], [mod_data(1)])
    with pytest.raises(SourceError, match="20"):
        source.resolve_files(manifest_for((1, 10), (2, 20)))


@responses.activate
def test_distribution_opt_out_requires_manual_download(source):
    stub_resolution([file_data(10, 1)], [mod_data(1, allowModDistribution=False)])
    file = source.resolve_files(manifest_for((1, 10)))[0]
    assert file.url is None
    assert file.manual_url == "https://www.curseforge.com/minecraft/mc-mods/mod-1/files/10"


@responses.activate
def test_missing_download_url_is_never_rebuilt(source):
    stub_resolution([file_data(10, 1, downloadUrl=None)], [mod_data(1)])
    file = source.resolve_files(manifest_for((1, 10)))[0]
    assert file.url is None
    assert file.manual_url


@responses.activate
def test_requests_are_batched(source):
    ids = list(range(1, 503))
    responses.post(f"{BASE}/v1/mods/files", json={"data": []})
    source.client.get_files(ids)
    assert [len(json.loads(c.request.body)["fileIds"]) for c in responses.calls] == [500, 2]
