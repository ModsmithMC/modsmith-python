"""HTTP session with retries, shared by everything that uses the network."""

import threading
import time
from collections.abc import Collection, Generator, Mapping
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from types import TracebackType
from typing import Any, Self

import requests

from ..errors import NetworkError

try:
    __version__ = version("modsmith")
except PackageNotFoundError:
    __version__ = "0.0.0"

DEFAULT_USER_AGENT = f"modsmith/{__version__} (https://github.com/PaPa-jun/Modsmith)"
DEFAULT_TIMEOUT = (10.0, 60.0)
MAX_RETRY_AFTER = 60.0
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
TRANSIENT_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def is_retryable(error: Exception) -> bool:
    """Return whether a failed request is worth repeating.

    Connection errors, timeouts, and HTTP 429 and 5xx responses are transient.
    """
    if isinstance(error, NetworkError):
        return error.status is None or error.status in RETRY_STATUS
    return isinstance(error, TRANSIENT_ERRORS)


@contextmanager
def session_scope(session: "Session | None") -> Generator["Session"]:
    """Yield ``session``, or a temporary `Session` closed on exit."""
    if session is not None:
        yield session
        return
    with Session() as owned:
        yield owned


def retry_delay(headers: Mapping[str, str]) -> float | None:
    """Return the delay a ``Retry-After`` header asks for, capped at one minute.

    Args:
        headers: The response headers.

    Returns:
        The delay in seconds, or None if there is no delay in seconds.
    """
    value = headers.get("Retry-After", "")
    return min(float(value), MAX_RETRY_AFTER) if value.isdigit() else None


class Session:
    """HTTP client with retries. Safe to share between threads.

    Each thread gets its own connection pool. Use it as a context manager, or
    call `close` when you are done.

    Args:
        user_agent: The ``User-Agent`` header sent with every request.
        attempts: How many times to try each request.
        backoff: Seconds to wait before the first retry. Doubles on each retry.
        timeout: The connect and read timeouts in seconds.
    """

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        attempts: int = 4,
        backoff: float = 1.0,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self.user_agent = user_agent
        self.attempts = attempts
        self.backoff = backoff
        self.timeout = timeout
        self._local = threading.local()
        self._lock = threading.Lock()
        self._sessions: list[requests.Session] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the connections of every thread.

        The session stays usable and reconnects on the next request.
        """
        with self._lock:
            for session in self._sessions:
                session.close()
            self._sessions.clear()
        self._local = threading.local()

    @property
    def http(self) -> requests.Session:
        """The calling thread's `requests.Session`, created on first use."""
        session: requests.Session | None = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = self.user_agent
            self._local.session = session
            with self._lock:
                self._sessions.append(session)
        return session

    def wait(self, attempt: int, delay: float | None = None) -> None:
        """Sleep before a retry.

        Args:
            attempt: The zero-based index of the retry.
            delay: Seconds the server asked for, instead of the normal backoff.
        """
        time.sleep(self.backoff * 2**attempt if delay is None else delay)

    def request(
        self, method: str, url: str, *, accept: Collection[int] = (), **kwargs: Any
    ) -> requests.Response:
        """Send a request, retrying transient failures.

        Retries stop once a response has been accepted, so reading a streamed
        body is not covered. A delay in ``Retry-After`` is respected, up to one
        minute.

        Args:
            method: The HTTP method.
            url: The URL.
            accept: Error statuses to return instead of raising.
            **kwargs: Passed to `requests.Session.request`.

        Returns:
            A successful response, or one with a status in ``accept``.

        Raises:
            NetworkError: The last attempt failed or returned an error status.
        """
        kwargs.setdefault("timeout", self.timeout)
        last = NetworkError(f"{method} {url} was not attempted")
        delay: float | None = None
        for attempt in range(self.attempts):
            if attempt:
                self.wait(attempt - 1, delay)
            delay = None
            try:
                response = self.http.request(method, url, **kwargs)
            except requests.RequestException as e:
                last = NetworkError(f"{method} {url} failed: {e}")
                if not is_retryable(e):
                    break
                continue
            if response.ok or response.status_code in accept:
                return response
            delay = retry_delay(response.headers)
            response.close()
            last = NetworkError(
                f"{method} {url} returned {response.status_code}", response.status_code
            )
            if not is_retryable(last):
                break
        raise last

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """Send a GET request and decode the JSON response.

        Args:
            url: The URL.
            **kwargs: Passed to `requests.Session.request`.

        Returns:
            The decoded body.

        Raises:
            NetworkError: The request failed or the body is not JSON.
        """
        return self._json(self.request("GET", url, **kwargs), url)

    def post_json(self, url: str, **kwargs: Any) -> Any:
        """Send a POST request and decode the JSON response.

        Args:
            url: The URL.
            **kwargs: Passed to `requests.Session.request`.

        Returns:
            The decoded body.

        Raises:
            NetworkError: The request failed or the body is not JSON.
        """
        return self._json(self.request("POST", url, **kwargs), url)

    def stream(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        *,
        accept: Collection[int] = (),
    ) -> requests.Response:
        """Open a streaming GET request, with the same retries as `request`.

        Failures while reading the body are not retried, because the caller
        has to decide how to resume.

        Args:
            url: The URL.
            headers: Extra request headers.
            accept: Error statuses to return instead of raising.

        Returns:
            The open response. Use it as a context manager.

        Raises:
            NetworkError: The last attempt failed or returned an error status.
        """
        return self.request("GET", url, accept=accept, headers=headers, stream=True)

    def _json(self, response: requests.Response, url: str) -> Any:
        """Decode a JSON response, raising `NetworkError` if it is invalid."""
        try:
            return response.json()
        except ValueError as e:
            raise NetworkError(f"Invalid JSON from {url}") from e
