import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from .._support import replace_file
from ..errors import Cancelled, DownloadError, IntegrityError, NetworkError
from ..progress import CancelToken, ProgressCallback, report
from ._resource import Resource, matches
from ._session import Session, is_retryable

logger = logging.getLogger(__name__)
CHUNK_SIZE = 65536
OnBytes = Callable[[int], None]


def _verify(resource: Resource, part: Path) -> None:
    if resource.size is not None and part.stat().st_size != resource.size:
        raise IntegrityError(f"Size mismatch for {resource.path.name}")
    if not matches(part, resource.hashes):
        raise IntegrityError(f"Hash mismatch for {resource.path.name}")


def _stream(
    url: str,
    resource: Resource,
    part: Path,
    session: Session,
    on_bytes: OnBytes,
    cancel: CancelToken | None,
) -> None:
    offset = part.stat().st_size if part.exists() else 0
    if resource.size is not None and offset >= resource.size:
        part.touch()  # an empty file has nothing to stream
        return
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with session.stream(url, headers) as response:
        if response.status_code == 416:
            part.unlink(missing_ok=True)
            raise NetworkError(f"Stale partial file for {url}", 503)
        if not response.ok:
            raise NetworkError(
                f"GET {url} returned {response.status_code}", response.status_code
            )
        append = offset > 0 and response.status_code == 206
        with open(part, "ab" if append else "wb") as file:
            for chunk in response.iter_content(CHUNK_SIZE):
                if cancel is not None:
                    cancel.check()
                file.write(chunk)
                on_bytes(len(chunk))


def _fetch(
    resource: Resource,
    session: Session,
    on_bytes: OnBytes,
    cancel: CancelToken | None,
) -> None:
    if resource.is_present():
        return
    if not resource.urls:
        raise DownloadError(f"{resource.path.name} has no download URL")
    resource.path.parent.mkdir(parents=True, exist_ok=True)
    part = resource.path.with_name(resource.path.name + ".part")

    last: Exception | None = None
    for url in resource.urls:
        for attempt in range(session.attempts):
            if attempt:
                session.wait(attempt - 1)
            if cancel is not None:
                cancel.check()
            try:
                _stream(url, resource, part, session, on_bytes, cancel)
                _verify(resource, part)
            except IntegrityError as e:
                part.unlink(missing_ok=True)
                last = e
                continue
            except (requests.RequestException, NetworkError) as e:
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

    Interrupted files resume from their `.part` file. All files are attempted
    even if some fail; `DownloadError.failures` then lists every failure.
    `progress` may be called from worker threads, one call at a time.
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
            report(progress, task, min(transferred, total_bytes), total_bytes, "byte")

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
