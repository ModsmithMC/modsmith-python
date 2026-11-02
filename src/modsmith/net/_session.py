import threading
import time
from importlib.metadata import PackageNotFoundError, version
from types import TracebackType
from typing import Any, Self

import requests

from ..errors import NetworkError

try:
    __version__ = version("modsmith")
except PackageNotFoundError:
    __version__ = "0.0.0"

DEFAULT_USER_AGENT = f"modsmith/{__version__} (https://github.com/PaPa-jun/CurseCraft)"
DEFAULT_TIMEOUT = (10.0, 60.0)
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
TRANSIENT_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def is_retryable(error: Exception) -> bool:
    if isinstance(error, NetworkError):
        return error.status is None or error.status in RETRY_STATUS
    return isinstance(error, TRANSIENT_ERRORS)


class Session:
    """HTTP client with retries. Safe to share between threads."""

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
        with self._lock:
            for session in self._sessions:
                session.close()
            self._sessions.clear()
        self._local = threading.local()

    @property
    def http(self) -> requests.Session:
        session: requests.Session | None = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = self.user_agent
            self._local.session = session
            with self._lock:
                self._sessions.append(session)
        return session

    def wait(self, attempt: int) -> None:
        time.sleep(self.backoff * 2**attempt)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last = NetworkError(f"{method} {url} was not attempted")
        for attempt in range(self.attempts):
            if attempt:
                self.wait(attempt - 1)
            try:
                response = self.http.request(method, url, **kwargs)
            except requests.RequestException as e:
                last = NetworkError(f"{method} {url} failed: {e}")
                if not is_retryable(e):
                    break
                continue
            if response.ok:
                return response
            last = NetworkError(
                f"{method} {url} returned {response.status_code}", response.status_code
            )
            if not is_retryable(last):
                break
        raise last

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self._json(self.request("GET", url, **kwargs), url)

    def post_json(self, url: str, **kwargs: Any) -> Any:
        return self._json(self.request("POST", url, **kwargs), url)

    def stream(self, url: str, headers: dict[str, str]) -> requests.Response:
        return self.http.get(url, headers=headers, stream=True, timeout=self.timeout)

    def _json(self, response: requests.Response, url: str) -> Any:
        try:
            return response.json()
        except ValueError as e:
            raise NetworkError(f"Invalid JSON from {url}") from e
