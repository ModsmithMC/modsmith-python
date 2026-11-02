import hashlib

import pytest
import requests
import responses

import modsmith as ms
from helpers import sha1
from modsmith.errors import Cancelled, DownloadError, NetworkError
from modsmith.net import Resource, download, file_hash

URL = "https://example.test/file.bin"
MIRROR = "https://mirror.test/file.bin"


def resource(path, data=None, url=URL, **kwargs):
    hashes = {"sha1": sha1(data)} if data is not None else None
    return Resource.of(url, path, hashes, **kwargs)


@responses.activate
def test_session_retries_server_errors_with_identifying_agent(session):
    responses.get(URL, status=503)
    responses.get(URL, json={"ok": True})
    assert session.get_json(URL) == {"ok": True}
    assert responses.calls[0].request.headers["User-Agent"].startswith("modsmith/")


@responses.activate
def test_session_does_not_retry_client_errors(session):
    responses.get(URL, status=404)
    with pytest.raises(NetworkError) as error:
        session.get_json(URL)
    assert error.value.status == 404
    assert len(responses.calls) == 1


@responses.activate
def test_session_retries_rate_limit_and_connection_errors(session):
    responses.get(URL, status=429)
    responses.get(URL, body=requests.ConnectionError("boom"))
    responses.get(URL, json=[1])
    assert session.get_json(URL) == [1]


@responses.activate
def test_invalid_json_is_reported(session):
    responses.get(URL, body="nope")
    with pytest.raises(NetworkError, match="Invalid JSON"):
        session.get_json(URL)


@responses.activate
def test_download_verifies_and_reports_bytes(session, tmp_path):
    data = b"payload"
    responses.get(URL, body=data)
    dest = tmp_path / "nested" / "file.bin"
    events = []
    download(resource(dest, data, size=len(data)), session=session, progress=events.append)
    assert dest.read_bytes() == data
    assert not dest.with_name("file.bin.part").exists()
    assert events[-1] == ms.Progress("download", len(data), len(data), "byte")


@responses.activate
def test_download_reports_files_when_sizes_are_unknown(session, tmp_path):
    responses.get(URL, body=b"x")
    events = []
    download(resource(tmp_path / "f"), session=session, progress=events.append)
    assert events == [ms.Progress("download", 1, 1, "file")]


@responses.activate
def test_download_skips_valid_file(session, tmp_path):
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"payload")
    download(resource(dest, b"payload"), session=session)
    assert len(responses.calls) == 0


@responses.activate
def test_download_replaces_corrupt_file(session, tmp_path):
    responses.get(URL, body=b"payload")
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"corrupt")
    download(resource(dest, b"payload"), session=session)
    assert dest.read_bytes() == b"payload"


@responses.activate
def test_download_prefers_strongest_hash(session, tmp_path):
    responses.get(URL, body=b"payload")
    hashes = {"sha1": "0" * 40, "sha512": hashlib.sha512(b"payload").hexdigest()}
    download(Resource.of(URL, tmp_path / "f", hashes), session=session)
    assert (tmp_path / "f").read_bytes() == b"payload"


@responses.activate
def test_download_falls_back_to_next_url(session, tmp_path):
    responses.get(URL, status=404)
    responses.get(MIRROR, body=b"payload")
    item = Resource((URL, MIRROR), tmp_path / "f", {"sha1": sha1(b"payload")})
    download(item, session=session)
    assert (tmp_path / "f").read_bytes() == b"payload"


@responses.activate
def test_download_resumes_with_range_request(session, tmp_path):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(data[:4])
    responses.get(URL, status=206, body=data[4:])
    download(resource(dest, data, size=len(data)), session=session)
    assert responses.calls[0].request.headers["Range"] == "bytes=4-"
    assert dest.read_bytes() == data


@responses.activate
def test_download_restarts_when_server_ignores_range(session, tmp_path):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(b"xxxx")
    responses.get(URL, status=200, body=data)
    download(resource(dest, data), session=session)
    assert dest.read_bytes() == data


@responses.activate
def test_download_retries_after_stale_partial(session, tmp_path):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    dest.with_name("file.bin.part").write_bytes(b"too-long-partial")
    responses.get(URL, status=416)
    responses.get(URL, status=200, body=data)
    download(resource(dest, data), session=session)
    assert dest.read_bytes() == data


@responses.activate
def test_hash_mismatch_retries_then_fails_clean(session, tmp_path):
    responses.get(URL, body=b"wrong")
    dest = tmp_path / "file.bin"
    with pytest.raises(DownloadError):
        download(resource(dest, b"right"), session=session)
    assert len(responses.calls) == session.attempts
    assert not dest.exists()
    assert not dest.with_name("file.bin.part").exists()


class Interrupted:
    status_code = 200
    ok = True

    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield from self.chunks
        if self.error:
            raise self.error


def test_interrupted_stream_keeps_partial_for_resume(session, tmp_path, monkeypatch):
    data = b"0123456789"
    dest = tmp_path / "file.bin"
    calls = []

    def stream(url, headers):
        calls.append(headers)
        return Interrupted([data[:4]], requests.exceptions.ChunkedEncodingError("cut"))

    session.attempts = 1
    monkeypatch.setattr(session, "stream", stream)
    with pytest.raises(DownloadError):
        download(resource(dest, data), session=session)
    assert dest.with_name("file.bin.part").read_bytes() == data[:4]
    with pytest.raises(DownloadError):
        download(resource(dest, data), session=session)
    assert calls[1] == {"Range": "bytes=4-"}


def test_cancel_stops_download_and_keeps_partial(session, tmp_path, monkeypatch):
    token = ms.CancelToken()
    dest = tmp_path / "file.bin"

    class Stream(Interrupted):
        def iter_content(self, size):
            yield b"abcd"
            token.cancel()
            yield b"efgh"

    monkeypatch.setattr(session, "stream", lambda url, headers: Stream([]))
    with pytest.raises(Cancelled):
        download(resource(dest), session=session, cancel=token)
    assert dest.with_name("file.bin.part").read_bytes() == b"abcd"


@responses.activate
def test_failures_are_collected_and_others_finish(session, tmp_path):
    good = "https://example.test/good"
    bad = "https://example.test/bad"
    responses.get(good, body=b"good")
    responses.get(bad, status=404)
    items = [Resource.of(good, tmp_path / "good"), Resource.of(bad, tmp_path / "bad")]
    with pytest.raises(DownloadError) as error:
        download(items, session=session, max_workers=2)
    assert len(error.value.failures) == 1
    assert (tmp_path / "good").read_bytes() == b"good"


@responses.activate
def test_resource_without_urls_fails(session, tmp_path):
    with pytest.raises(DownloadError):
        download(Resource((), tmp_path / "f"), session=session)


@responses.activate
def test_download_creates_its_own_session(tmp_path):
    responses.get(URL, body=b"x")
    download(resource(tmp_path / "f"))
    assert (tmp_path / "f").read_bytes() == b"x"


def test_file_hash_supports_md5(tmp_path):
    path = tmp_path / "a"
    path.write_bytes(b"x")
    assert file_hash(path, "md5") == hashlib.md5(b"x").hexdigest()


def test_cancel_token():
    token = ms.CancelToken()
    token.check()
    token.cancel()
    assert token.cancelled
    with pytest.raises(Cancelled):
        token.check()


def test_every_error_derives_from_base():
    for name in ms.errors.__all__:
        assert issubclass(getattr(ms.errors, name), ms.errors.ModsmithError)
