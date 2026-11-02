import hashlib

import pytest

import modsmith as ms
from modsmith.errors import Cancelled, DownloadError
from modsmith.net import Resource, download, file_hash
from modsmith.net._download import CHUNK_SIZE
from tests.lib.builders import sha1
from tests.lib.server import Reply


def part_of(path):
    return path.with_name(path.name + ".part")


def test_downloads_verifies_and_reports_bytes(server, session, tmp_path):
    data = b"payload"
    url = server.add_body("/file", data)
    dest = tmp_path / "nested" / "file"
    events = []
    item = Resource.of(url, dest, {"sha1": sha1(data)}, len(data))
    download(item, session=session, progress=events.append)
    assert dest.read_bytes() == data
    assert not part_of(dest).exists()
    assert events[-1] == ms.Progress("download", len(data), len(data), "byte")


def test_reports_files_when_sizes_are_unknown(server, session, tmp_path):
    url = server.add_body("/file", b"x")
    events = []
    download(Resource.of(url, tmp_path / "f"), session=session, progress=events.append)
    assert events == [ms.Progress("download", 1, 1, "file")]


def test_skips_valid_file(server, session, tmp_path):
    url = server.add_body("/file", b"new")
    dest = tmp_path / "f"
    dest.write_bytes(b"old")
    download(Resource.of(url, dest, {"sha1": sha1(b"old")}), session=session)
    assert server.hits("/file") == []


def test_replaces_corrupt_file(server, session, tmp_path):
    url = server.add_body("/file", b"payload")
    dest = tmp_path / "f"
    dest.write_bytes(b"corrupt")
    download(Resource.of(url, dest, {"sha1": sha1(b"payload")}), session=session)
    assert dest.read_bytes() == b"payload"


def test_verifies_the_strongest_hash(server, session, tmp_path):
    url = server.add_body("/file", b"payload")
    hashes = {"sha1": "0" * 40, "sha512": hashlib.sha512(b"payload").hexdigest()}
    download(Resource.of(url, tmp_path / "f", hashes), session=session)
    assert (tmp_path / "f").read_bytes() == b"payload"


def test_falls_back_to_the_next_url(server, session, tmp_path):
    bad = server.add("/bad", Reply(status=404))
    good = server.add_body("/good", b"payload")
    item = Resource((bad, good), tmp_path / "f", {"sha1": sha1(b"payload")})
    download(item, session=session)
    assert (tmp_path / "f").read_bytes() == b"payload"


def test_resumes_with_a_range_request(server, session, tmp_path):
    data = b"0123456789"
    url = server.add_body("/file", data)
    dest = tmp_path / "f"
    part_of(dest).write_bytes(data[:4])
    download(Resource.of(url, dest, {"sha1": sha1(data)}, len(data)), session=session)
    assert server.requests[0].headers["Range"] == "bytes=4-"
    assert dest.read_bytes() == data


def test_restarts_when_server_ignores_range(server, session, tmp_path):
    data = b"0123456789"
    url = server.add("/file", Reply(data, ranges=False))
    dest = tmp_path / "f"
    part_of(dest).write_bytes(b"xxxx")
    download(Resource.of(url, dest, {"sha1": sha1(data)}), session=session)
    assert dest.read_bytes() == data


def test_recovers_from_a_stale_partial_file(server, session, tmp_path):
    data = b"0123456789"
    url = server.add_body("/file", data)
    dest = tmp_path / "f"
    part_of(dest).write_bytes(b"longer-than-the-real-file")
    download(Resource.of(url, dest, {"sha1": sha1(data)}), session=session)
    assert dest.read_bytes() == data


def test_dropped_connection_is_resumed_on_retry(server, session, tmp_path):
    data = bytes(range(256)) * 1000
    url = server.add("/file", Reply(data, drop_after=CHUNK_SIZE + 10), Reply(data))
    dest = tmp_path / "f"
    download(Resource.of(url, dest, {"sha1": sha1(data)}), session=session)
    assert dest.read_bytes() == data
    assert server.requests[1].headers["Range"] == f"bytes={CHUNK_SIZE}-"


def test_failed_download_keeps_complete_chunks_for_next_run(server, session, tmp_path):
    data = bytes(range(256)) * 1000
    url = server.add("/file", Reply(data, drop_after=CHUNK_SIZE + 10))
    dest = tmp_path / "f"
    session.attempts = 1
    item = Resource.of(url, dest, {"sha1": sha1(data)})
    with pytest.raises(DownloadError):
        download(item, session=session)
    assert part_of(dest).read_bytes() == data[:CHUNK_SIZE]
    assert not dest.exists()

    server.add_body("/file", data)
    download(item, session=session)
    assert dest.read_bytes() == data
    assert server.requests[-1].headers["Range"] == f"bytes={CHUNK_SIZE}-"


def test_hash_mismatch_retries_then_fails_clean(server, session, tmp_path):
    url = server.add_body("/file", b"wrong")
    dest = tmp_path / "f"
    with pytest.raises(DownloadError):
        download(Resource.of(url, dest, {"sha1": sha1(b"right")}), session=session)
    assert len(server.hits("/file")) == session.attempts
    assert not dest.exists()
    assert not part_of(dest).exists()


def test_cancel_stops_download_and_keeps_partial(server, session, tmp_path):
    data = b"x" * (1 << 21)
    url = server.add_body("/file", data)
    dest = tmp_path / "f"
    token = ms.CancelToken()

    def cancel_after_first_chunk(event):
        token.cancel()

    item = Resource.of(url, dest, size=len(data))
    with pytest.raises(Cancelled):
        download(item, session=session, cancel=token, progress=cancel_after_first_chunk)
    assert not dest.exists()
    assert 0 < part_of(dest).stat().st_size < len(data)


def test_failures_are_collected_and_others_finish(server, session, tmp_path):
    good = server.add_body("/good", b"good")
    bad = server.add("/bad", Reply(status=404))
    items = [Resource.of(good, tmp_path / "g"), Resource.of(bad, tmp_path / "b")]
    with pytest.raises(DownloadError) as error:
        download(items, session=session, max_workers=2)
    assert len(error.value.failures) == 1
    assert (tmp_path / "g").read_bytes() == b"good"


def test_resource_without_urls_fails(session, tmp_path):
    with pytest.raises(DownloadError):
        download(Resource((), tmp_path / "f"), session=session)


def test_creates_its_own_session_when_none_is_given(server, tmp_path):
    url = server.add_body("/file", b"x")
    download(Resource.of(url, tmp_path / "f"))
    assert (tmp_path / "f").read_bytes() == b"x"


def test_file_hash_supports_md5(tmp_path):
    path = tmp_path / "a"
    path.write_bytes(b"x")
    assert file_hash(path, "md5") == hashlib.md5(b"x").hexdigest()
