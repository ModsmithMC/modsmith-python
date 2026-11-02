import socket
import time

import pytest

from modsmith.errors import NetworkError
from modsmith.net._session import MAX_RETRY_AFTER, retry_delay
from tests.lib.server import Reply


def test_retries_server_errors_and_identifies_itself(server, session):
    url = server.add("/data", Reply(status=503), Reply(b'{"ok": true}'))
    assert session.get_json(url) == {"ok": True}
    assert len(server.hits("/data")) == 2
    assert server.requests[0].headers["User-Agent"].startswith("modsmith/")


def test_retries_rate_limits(server, session):
    url = server.add("/data", Reply(status=429), Reply(b"[1]"))
    assert session.get_json(url) == [1]


def test_waits_as_long_as_the_server_asks(server, session):
    busy = Reply(status=429, headers={"Retry-After": "1"})
    url = server.add("/data", busy, Reply(b"[1]"))
    started = time.monotonic()
    assert session.get_json(url) == [1]
    assert time.monotonic() - started >= 1


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "2"}, 2),
        ({"Retry-After": "86400"}, MAX_RETRY_AFTER),
        ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
        ({}, None),
    ],
)
def test_retry_delay(headers, expected):
    assert retry_delay(headers) == expected


def test_stream_retries_before_the_body(server, session):
    url = server.add("/data", Reply(status=503), Reply(b"body"))
    with session.stream(url) as response:
        assert response.content == b"body"
    assert len(server.hits("/data")) == 2


def test_stream_raises_on_error_status(server, session):
    url = server.add("/data", Reply(status=404))
    with pytest.raises(NetworkError) as error:
        session.stream(url)
    assert error.value.status == 404


def test_stream_returns_accepted_status(server, session):
    url = server.add("/data", Reply(status=416))
    with session.stream(url, accept=(416,)) as response:
        assert response.status_code == 416
    assert len(server.hits("/data")) == 1


def test_does_not_retry_client_errors(server, session):
    url = server.add("/data", Reply(status=404))
    with pytest.raises(NetworkError) as error:
        session.get_json(url)
    assert error.value.status == 404
    assert len(server.hits("/data")) == 1


def test_gives_up_after_all_attempts(server, session):
    url = server.add("/data", Reply(status=503))
    with pytest.raises(NetworkError):
        session.get_json(url)
    assert len(server.hits("/data")) == session.attempts


def test_refused_connection_is_retried_then_reported(session):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(NetworkError):
        session.get_json(f"http://127.0.0.1:{port}/data")


def test_invalid_json_is_reported(server, session):
    url = server.add_body("/data", b"nope")
    with pytest.raises(NetworkError, match="Invalid JSON"):
        session.get_json(url)
