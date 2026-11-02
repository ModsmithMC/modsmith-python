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


def test_progress_counts_files_that_are_already_valid(server, session, tmp_path):
    (tmp_path / "old").write_bytes(b"old")
    new = server.add_body("/new", b"newer")
    items = [
        Resource.of(server.url("/old"), tmp_path / "old", {"sha1": sha1(b"old")}, 3),
        Resource.of(new, tmp_path / "new", {"sha1": sha1(b"newer")}, 5),
    ]
    events = []
    download(items, session=session, progress=events.append)
    assert max(event.current for event in events) == 8
    assert events[-1].total == 8


def test_progress_counts_a_resumed_file(server, session, tmp_path):
    data = b"0123456789"
    url = server.add_body("/file", data)
    dest = tmp_path / "f"
    part_of(dest).write_bytes(data[:4])
    events = []
    item = Resource.of(url, dest, {"sha1": sha1(data)}, len(data))
    download(item, session=session, progress=events.append)
    assert events[0].current == 4
    assert events[-1].current == len(data)


def test_progress_starts_over_when_a_file_is_replaced(server, session, tmp_path):
    data = b"0123456789"
    url = server.add("/file", Reply(b"wrongwrong"), Reply(data))
    events = []
    item = Resource.of(url, tmp_path / "f", {"sha1": sha1(data)}, len(data))
    download(item, session=session, progress=events.append)
    assert [event.current for event in events] == [10, 0, 10]


def test_reports_files_when_sizes_are_unknown(server, session, tmp_path):
    url = server.add_body("/file", b"x")
    events = []
    download(Resource.of(url, tmp_path / "f"), session=session, progress=events.append)
    assert events == [ms.Progress("download", 1, 1, "file")]


def test_downloads_an_empty_file(server, session, tmp_path):
    url = server.add_body("/file", b"")
    dest = tmp_path / "f"
    download(Resource.of(url, dest, {"sha1": sha1(b"")}, 0), session=session)
    assert dest.read_bytes() == b""
    assert not part_of(dest).exists()


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


def test_server_failure_is_not_retried_twice_over(server, session, tmp_path):
    url = server.add("/file", Reply(status=503))
    with pytest.raises(DownloadError):
        download(Resource.of(url, tmp_path / "f"), session=session)
    assert len(server.hits("/file")) == session.attempts


def test_moves_to_the_next_url_after_server_failures(server, session, tmp_path):
    bad = server.add("/bad", Reply(status=503))
    good = server.add_body("/good", b"payload")
    download(Resource((bad, good), tmp_path / "f"), session=session)
    assert (tmp_path / "f").read_bytes() == b"payload"
    assert len(server.hits("/bad")) == session.attempts


def test_resume_gets_the_whole_file_if_it_changed(server, session, tmp_path):
    old = bytes(range(256)) * 1000
    new = bytes(reversed(range(256))) * 1000
    url = server.add(
        "/file",
        Reply(old, headers={"ETag": '"v1"'}, drop_after=CHUNK_SIZE + 10),
        Reply(new, headers={"ETag": '"v2"'}),
    )
    download(Resource.of(url, tmp_path / "f", {"sha1": sha1(new)}), session=session)
    assert (tmp_path / "f").read_bytes() == new
    assert server.requests[1].headers["If-Range"] == '"v1"'
    assert len(server.requests) == 2


def test_weak_etag_is_not_used_to_resume(server, session, tmp_path):
    data = bytes(range(256)) * 1000
    url = server.add(
        "/file",
        Reply(data, headers={"ETag": 'W/"v1"'}, drop_after=CHUNK_SIZE + 10),
        Reply(data),
    )
    download(Resource.of(url, tmp_path / "f"), session=session)
    assert (tmp_path / "f").read_bytes() == data
    assert "If-Range" not in server.requests[1].headers


def test_range_at_the_wrong_offset_is_rejected(server, session, tmp_path):
    data = bytes(range(256)) * 1000
    wrong = Reply(data, 206, {"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"})
    url = server.add(
        "/file", Reply(data, drop_after=CHUNK_SIZE + 10), wrong, Reply(data)
    )
    download(Resource.of(url, tmp_path / "f"), session=session)
    assert (tmp_path / "f").read_bytes() == data


def test_leftover_partial_without_a_hash_is_discarded(server, session, tmp_path):
    url = server.add_body("/file", b"0123456789")
    dest = tmp_path / "f"
    part_of(dest).write_bytes(b"xxxx")
    download(Resource.of(url, dest), session=session)
    assert dest.read_bytes() == b"0123456789"
    assert "Range" not in server.requests[0].headers


def test_dropped_connection_is_resumed_on_retry(server, session, tmp_path):
    data = bytes(range(256)) * 1000
    url = server.add("/file", Reply(data, drop_after=CHUNK_SIZE + 10), Reply(data))
    dest = tmp_path / "f"
    download(Resource.of(url, dest, {"sha1": sha1(data)}), session=session)
    assert dest.read_bytes() == data
    assert server.requests[1].headers["Range"] == f"bytes={CHUNK_SIZE}-"
    assert server.requests[1].headers.get("If-Range") is None


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
