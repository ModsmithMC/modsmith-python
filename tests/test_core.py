import hashlib

import pytest
import requests
import responses

from cursecraft.core.download import Downloader, DownloadTask, file_hash
from cursecraft.core.errors import ConfigError, DownloadError, HttpError
from cursecraft.core.events import Progress, StepFinished, StepSkipped, StepStarted
from cursecraft.core.http import USER_AGENT, HttpClient
from cursecraft.core.paths import MavenCoord, maven_path, safe_name
from cursecraft.core.settings import Settings
from cursecraft.core.steps import FunctionStep, run_steps

URL = "https://example.test/file.bin"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


@pytest.fixture
def http():
    return HttpClient(backoff=0)


@pytest.mark.parametrize(
    ("coord", "path"),
    [
        ("net.minecraft:client:1.21", "net/minecraft/client/1.21/client-1.21.jar"),
        (
            "net.minecraftforge:forge:1.21-52:shim",
            "net/minecraftforge/forge/1.21-52/forge-1.21-52-shim.jar",
        ),
        ("de.oceanlabs:mcp:1.21:mappings@tsrg", "de/oceanlabs/mcp/1.21/mcp-1.21-mappings.tsrg"),
        ("a.b:c:1@zip", "a/b/c/1/c-1.zip"),
    ],
)
def test_maven_path(coord, path):
    assert maven_path(coord) == path


@pytest.mark.parametrize("coord", ["a:b", "a:b:c:d:e", "a:b:c@d@e"])
def test_invalid_maven_coord(coord):
    with pytest.raises(ValueError):
        MavenCoord.parse(coord)


def test_safe_name_strips_invalid_characters():
    assert safe_name('Pack: "One"/Two.') == "Pack- -One--Two"
    assert safe_name("...") == "instance"


def test_settings_defaults_instances_under_minecraft(tmp_path):
    settings = Settings(minecraft_dir=tmp_path)
    assert settings.instances_dir == tmp_path / "cursecraft" / "instances"


def test_settings_load_file_and_env(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        f'minecraft_dir = "{tmp_path.as_posix()}"\nmax_workers = 2\n'
        'curseforge_api_key = "from-file"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CURSECRAFT_API_KEY", "from-env")
    settings = Settings.load(config)
    assert settings.minecraft_dir == tmp_path
    assert settings.max_workers == 2
    assert settings.curseforge_api_key == "from-env"


def test_settings_rejects_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("CURSECRAFT_API_KEY", raising=False)
    config = tmp_path / "config.toml"
    config.write_text("nope = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Settings.load(config)


def test_run_steps_skips_done_and_reports_events():
    ran, events = [], []
    steps = [
        FunctionStep("a", lambda emit: ran.append("a"), lambda: True),
        FunctionStep("b", lambda emit: ran.append("b")),
    ]
    run_steps(steps, events.append)
    assert ran == ["b"]
    assert events == [
        StepSkipped("a", 1, 2),
        StepStarted("b", 2, 2),
        StepFinished("b", 2, 2),
    ]


@responses.activate
def test_http_retries_server_errors(http):
    responses.get(URL, status=503)
    responses.get(URL, json={"ok": True})
    assert http.get_json(URL) == {"ok": True}
    assert responses.calls[0].request.headers["User-Agent"] == USER_AGENT


@responses.activate
def test_http_does_not_retry_client_errors(http):
    responses.get(URL, status=404)
    with pytest.raises(HttpError) as error:
        http.get_json(URL)
    assert error.value.status == 404
    assert len(responses.calls) == 1


@responses.activate
def test_http_retries_rate_limit_and_connection_errors(http):
    responses.get(URL, status=429)
    responses.get(URL, body=requests.ConnectionError("boom"))
    responses.get(URL, json=[1])
    assert http.get_json(URL) == [1]
    assert len(responses.calls) == 3


@responses.activate
def test_fetch_verifies_and_reports_progress(http, tmp_path):
    data = b"payload"
    responses.get(URL, body=data, headers={"Content-Length": str(len(data))})
    dest = tmp_path / "nested" / "file.bin"
    events = []
    Downloader(http).fetch(DownloadTask(URL, dest, sha1(data)), events.append)
    assert dest.read_bytes() == data
    assert not dest.with_name("file.bin.part").exists()
    assert events[-1] == Progress("file.bin", len(data), len(data), "byte")


@responses.activate
def test_fetch_skips_valid_file(http, tmp_path):
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"payload")
    Downloader(http).fetch(DownloadTask(URL, dest, sha1(b"payload")))
    assert len(responses.calls) == 0


@responses.activate
def test_fetch_replaces_corrupt_file(http, tmp_path):
    responses.get(URL, body=b"payload")
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"corrupt")
    Downloader(http).fetch(DownloadTask(URL, dest, sha1(b"payload")))
    assert dest.read_bytes() == b"payload"


@responses.activate
def test_fetch_resumes_with_range_request(http, tmp_path):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(data[:4])
    responses.get(URL, status=206, body=data[4:], headers={"Content-Length": "6"})
    Downloader(http).fetch(DownloadTask(URL, dest, sha1(data), size=len(data)))
    assert responses.calls[0].request.headers["Range"] == "bytes=4-"
    assert dest.read_bytes() == data


@responses.activate
def test_fetch_restarts_when_server_ignores_range(http, tmp_path):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(b"xxxx")
    responses.get(URL, status=200, body=data)
    Downloader(http).fetch(DownloadTask(URL, dest, sha1(data)))
    assert dest.read_bytes() == data


@responses.activate
def test_fetch_retries_after_stale_partial_file(http, tmp_path):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(b"too-long-partial")
    responses.get(URL, status=416)
    responses.get(URL, status=200, body=data)
    Downloader(http).fetch(DownloadTask(URL, dest, sha1(data)))
    assert dest.read_bytes() == data


@responses.activate
def test_fetch_retries_hash_mismatch_then_fails_clean(http, tmp_path):
    responses.get(URL, body=b"wrong")
    dest = tmp_path / "file.bin"
    with pytest.raises(DownloadError):
        Downloader(http).fetch(DownloadTask(URL, dest, sha1(b"right")))
    assert len(responses.calls) == http.attempts
    assert not dest.exists()
    assert not dest.with_name("file.bin.part").exists()


@responses.activate
def test_fetch_does_not_retry_missing_file(http, tmp_path):
    responses.get(URL, status=404)
    with pytest.raises(DownloadError):
        Downloader(http).fetch(DownloadTask(URL, tmp_path / "file.bin"))
    assert len(responses.calls) == 1


def test_interrupted_stream_keeps_partial_file_for_resume(http, tmp_path):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    part = dest.with_name("file.bin.part")

    class Interrupted:
        status_code = 200
        ok = True
        headers = {"Content-Length": "10"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, size):
            yield data[:4]
            raise requests.exceptions.ChunkedEncodingError("cut off")

    calls = []

    def fake_get(url, headers, stream, timeout):
        calls.append(headers)
        return Interrupted()

    http.attempts = 1
    http.session.get = fake_get
    with pytest.raises(DownloadError):
        Downloader(http).fetch(DownloadTask(URL, dest, sha1(data)))
    assert part.read_bytes() == data[:4]
    assert not dest.exists()

    with pytest.raises(DownloadError):
        Downloader(http).fetch(DownloadTask(URL, dest, sha1(data)))
    assert calls[1] == {"Range": "bytes=4-"}


@responses.activate
def test_fetch_all_collects_failures_and_finishes_the_rest(http, tmp_path):
    good = "https://example.test/good"
    bad = "https://example.test/bad"
    responses.get(good, body=b"good")
    responses.get(bad, status=404)
    tasks = [
        DownloadTask(good, tmp_path / "good"),
        DownloadTask(bad, tmp_path / "bad"),
    ]
    with pytest.raises(DownloadError) as error:
        Downloader(http, max_workers=2).fetch_all(tasks)
    assert len(error.value.failures) == 1
    assert (tmp_path / "good").read_bytes() == b"good"


def test_file_hash_supports_md5(tmp_path):
    path = tmp_path / "a"
    path.write_bytes(b"x")
    assert file_hash(path, "md5") == hashlib.md5(b"x").hexdigest()
