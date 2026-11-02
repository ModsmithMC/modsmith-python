import threading
import time
from typing import Any

import requests

from .. import __version__
from .errors import HttpError

USER_AGENT = f"CurseCraft/{__version__} (https://github.com/PaPa-jun/CurseCraft)"
TIMEOUT = (10, 60)
RETRY_STATUS = {429, 500, 502, 503, 504}


def is_retryable(error: Exception) -> bool:
    if isinstance(error, HttpError):
        return error.status is None or error.status in RETRY_STATUS
    return isinstance(
        error,
        requests.ConnectionError | requests.Timeout | requests.exceptions.ChunkedEncodingError,
    )


class HttpClient:
    def __init__(self, attempts: int = 4, backoff: float = 1.0) -> None:
        self.attempts = attempts
        self.backoff = backoff
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
            self._local.session = session
        return session

    def wait(self, attempt: int) -> None:
        time.sleep(self.backoff * 2**attempt)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", TIMEOUT)
        last: Exception | None = None
        for attempt in range(self.attempts):
            if attempt:
                self.wait(attempt - 1)
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as e:
                last = HttpError(f"{method} {url} failed: {e}")
                if not is_retryable(e):
                    break
                continue
            if response.ok:
                return response
            last = HttpError(
                f"{method} {url} returned {response.status_code}", response.status_code
            )
            if not is_retryable(last):
                break
        raise last

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self._json(self.request("GET", url, **kwargs), url)

    def post_json(self, url: str, **kwargs: Any) -> Any:
        return self._json(self.request("POST", url, **kwargs), url)

    def _json(self, response: requests.Response, url: str) -> Any:
        try:
            return response.json()
        except ValueError as e:
            raise HttpError(f"Invalid JSON from {url}") from e
