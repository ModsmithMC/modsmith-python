"""Parallel downloads with verification and resume."""

import logging
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from .._support import replace_file
from ..errors import Cancelled, DownloadError, IntegrityError, NetworkError
from ..progress import CancelToken, ProgressCallback, report
from ._resource import Resource, matches, strongest_hash
from ._session import Session, is_retryable

logger = logging.getLogger(__name__)
CHUNK_SIZE = 65536
OnBytes = Callable[[int], None]


class _Meter:
    """Tracks how many bytes of one file count toward the overall progress."""

    def __init__(self, on_bytes: OnBytes) -> None:
        self.on_bytes = on_bytes
        self.counted = 0

    def add(self, count: int) -> None:
        """Count more bytes. A negative count takes bytes back."""
        if count:
            self.counted += count
            self.on_bytes(count)

    def reset(self, count: int) -> None:
        """Set the count, for a file that was skipped, resumed or restarted."""
        self.add(count - self.counted)


def _verify(resource: Resource, part: Path) -> None:
    """Check a finished ``.part`` file, raising `IntegrityError` if it is wrong."""
    if resource.size is not None and part.stat().st_size != resource.size:
        raise IntegrityError(f"Size mismatch for {resource.path.name}")
    if not matches(part, resource.hashes):
        raise IntegrityError(f"Hash mismatch for {resource.path.name}")


def _range_start(response: requests.Response) -> int | None:
    """Return where a partial response starts, if it says."""
    match = re.match(r"bytes (\d+)-", response.headers.get("Content-Range", ""))
    return int(match[1]) if match else None


def _validator(response: requests.Response) -> str | None:
    """Return a value that identifies this version of a file for ``If-Range``."""
    etag = response.headers.get("ETag")
    # ``If-Range`` only works with strong validators.
    if etag and not etag.startswith("W/"):
        return etag
    return response.headers.get("Last-Modified")


def _stream(
    url: str,
    resource: Resource,
    part: Path,
    session: Session,
    meter: _Meter,
    cancel: CancelToken | None,
    validators: dict[str, str],
) -> None:
    """Fetch one URL into ``part``, continuing from what is already there.

    ``validators`` remembers which version of the file each URL served, so a
    resume cannot join two versions.
    """
    offset = part.stat().st_size if part.exists() else 0
    if resource.size is not None and offset >= resource.size:
        part.touch()  # an empty file has nothing to stream
        meter.reset(offset)
        return
    headers: dict[str, str] = {}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        if url in validators:
            headers["If-Range"] = validators[url]
    with session.stream(url, headers, accept=(416,)) as response:
        if response.status_code == 416:
            raise IntegrityError(f"Stale partial file for {url}")
        # A 200 means the server sent the whole file, either because it ignored
        # the range or because the file changed.
        resuming = offset > 0 and response.status_code == 206
        if resuming and _range_start(response) not in (None, offset):
            raise IntegrityError(f"Wrong range from {url}")
        validator = _validator(response)
        if validator:
            validators[url] = validator
        meter.reset(offset if resuming else 0)
        with open(part, "ab" if resuming else "wb") as file:
            for chunk in response.iter_content(CHUNK_SIZE):
                if cancel is not None:
                    cancel.check()
                file.write(chunk)
                meter.add(len(chunk))


def _fetch(
    resource: Resource,
    session: Session,
    on_bytes: OnBytes,
    cancel: CancelToken | None,
) -> None:
    """Download one resource, trying each URL in turn.

    `Session.stream` has already retried a failure to connect, so that moves on
    to the next URL. Only a broken transfer or a bad file is retried here.

    Raises:
        DownloadError: Every URL failed.
        Cancelled: ``cancel`` was triggered.
    """
    meter = _Meter(on_bytes)
    if resource.is_present():
        meter.reset(resource.size or 0)
        return
    if not resource.urls:
        raise DownloadError(f"{resource.path.name} has no download URL")
    resource.path.parent.mkdir(parents=True, exist_ok=True)
    part = resource.path.with_name(resource.path.name + ".part")
    # Without a hash, nothing could prove a leftover file is the same version.
    if strongest_hash(resource.hashes) is None:
        part.unlink(missing_ok=True)

    validators: dict[str, str] = {}
    last: Exception | None = None
    for url in resource.urls:
        for attempt in range(session.attempts):
            if attempt:
                session.wait(attempt - 1)
            if cancel is not None:
                cancel.check()
            try:
                _stream(url, resource, part, session, meter, cancel, validators)
                _verify(resource, part)
            except IntegrityError as e:
                part.unlink(missing_ok=True)
                last = e
                continue
            except NetworkError as e:
                last = e
                break
            except requests.RequestException as e:
                last = e
                if not is_retryable(e):
                    break
                continue
            replace_file(part, resource.path)
            return
        logger.warning("Download from %s failed: %s", url, last)
    raise DownloadError(f"Failed to download {resource.path.name}: {last}") from last


def download(
    resources: Resource | Iterable[Resource],
    *,
    session: Session | None = None,
    max_workers: int = 8,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    task: str = "download",
) -> None:
    """Download resources in parallel, skipping files that are already valid.

    Interrupted files resume from their ``.part`` file. All files are attempted
    even if some fail. Resources with the same path are downloaded once.

    Args:
        resources: One resource, or several.
        session: The session to use. A temporary one is created if omitted.
        max_workers: How many files to download at once.
        progress: Called with byte counts if every size is known, otherwise with
            file counts. It may be called from worker threads, one at a time.
        cancel: Stops the downloads and keeps partial files for later.
        task: The task name reported to ``progress``.

    Raises:
        DownloadError: A file failed. `DownloadError.failures` lists every failure.
        Cancelled: ``cancel`` was triggered.
    """
    items = [resources] if isinstance(resources, Resource) else list(resources)
    unique = list({resource.path: resource for resource in items}.values())
    if session is None:
        with Session() as owned:
            return download(
                unique,
                session=owned,
                max_workers=max_workers,
                progress=progress,
                cancel=cancel,
                task=task,
            )

    sizes = [resource.size for resource in unique]
    by_bytes = bool(unique) and all(size is not None for size in sizes)
    total_bytes = sum(size or 0 for size in sizes)
    lock = threading.Lock()
    transferred = 0

    def on_bytes(count: int) -> None:
        nonlocal transferred
        if not by_bytes:
            return
        with lock:
            transferred += count
            done = min(max(transferred, 0), total_bytes)
            report(progress, task, done, total_bytes, "byte")

    failures: list[str] = []
    finished = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: dict[Future[None], Resource] = {
            executor.submit(_fetch, resource, session, on_bytes, cancel): resource
            for resource in unique
        }
        for future in as_completed(futures):
            error = future.exception()
            if isinstance(error, Cancelled):
                for other in futures:
                    other.cancel()
                raise error
            if isinstance(error, DownloadError):
                failures.append(str(error))
            elif error is not None:
                raise error
            finished += 1
            if not by_bytes:
                with lock:
                    report(progress, task, finished, len(unique), "file")
    if failures:
        raise DownloadError(
            f"{len(failures)} of {len(unique)} downloads failed", failures
        )
