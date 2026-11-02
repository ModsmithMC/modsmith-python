import hashlib
import os
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests

from .errors import DownloadError, HashMismatchError, HttpError
from .events import Emit, Progress, null_emit
from .http import HttpClient, is_retryable


def file_hash(path: Path, algo: str = "sha1") -> str:
    digest = hashlib.new(algo)
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DownloadTask:
    url: str
    dest: Path
    hash: str | None = None
    algo: str = "sha1"
    size: int | None = None

    def is_satisfied(self) -> bool:
        if not self.dest.is_file():
            return False
        if self.size is not None and self.dest.stat().st_size != self.size:
            return False
        return self.hash is None or file_hash(self.dest, self.algo) == self.hash.lower()


class Downloader:
    def __init__(
        self, http: HttpClient, max_workers: int = 8, chunk_size: int = 65536
    ) -> None:
        self.http = http
        self.max_workers = max_workers
        self.chunk_size = chunk_size

    def fetch(self, task: DownloadTask, emit: Emit = null_emit) -> Path:
        if task.is_satisfied():
            return task.dest
        task.dest.parent.mkdir(parents=True, exist_ok=True)
        part = task.dest.with_name(task.dest.name + ".part")

        last: Exception | None = None
        for attempt in range(self.http.attempts):
            if attempt:
                self.http.wait(attempt - 1)
            try:
                self._stream(task, part, emit)
                self._verify(task, part)
            except HashMismatchError as e:
                part.unlink(missing_ok=True)
                last = e
                continue
            except (requests.RequestException, HttpError) as e:
                last = e
                if not is_retryable(e):
                    break
                continue
            os.replace(part, task.dest)
            return task.dest
        raise DownloadError(f"Failed to download {task.url}: {last}") from last

    def _stream(self, task: DownloadTask, part: Path, emit: Emit) -> None:
        offset = part.stat().st_size if part.exists() else 0
        if task.size is not None and offset >= task.size:
            return
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        response = self.http.session.get(
            task.url, headers=headers, stream=True, timeout=(10, 60)
        )
        with response:
            if response.status_code == 416:
                part.unlink(missing_ok=True)
                raise HttpError(f"Stale partial file for {task.url}", 503)
            if not response.ok:
                raise HttpError(
                    f"GET {task.url} returned {response.status_code}",
                    response.status_code,
                )
            append = offset > 0 and response.status_code == 206
            current = offset if append else 0
            length = response.headers.get("Content-Length")
            total = current + int(length) if length else task.size
            with open(part, "ab" if append else "wb") as file:
                for chunk in response.iter_content(self.chunk_size):
                    file.write(chunk)
                    current += len(chunk)
                    emit(Progress(task.dest.name, current, total, "byte"))

    def _verify(self, task: DownloadTask, part: Path) -> None:
        if task.size is not None and part.stat().st_size != task.size:
            raise HashMismatchError(f"Size mismatch for {task.dest.name}")
        if task.hash is not None and file_hash(part, task.algo) != task.hash.lower():
            raise HashMismatchError(f"Hash mismatch for {task.dest.name}")

    def fetch_all(
        self,
        tasks: Iterable[DownloadTask],
        emit: Emit = null_emit,
        label: str = "Downloading",
    ) -> None:
        unique = list({task.dest: task for task in tasks}.values())
        lock = threading.Lock()
        finished = 0
        failures: list[str] = []
        emit(Progress(label, 0, len(unique), "file"))
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.fetch, task): task for task in unique}
            for future in as_completed(futures):
                try:
                    future.result()
                except DownloadError as e:
                    failures.append(str(e))
                with lock:
                    finished += 1
                    emit(Progress(label, finished, len(unique), "file"))
        if failures:
            raise DownloadError(
                f"{len(failures)} of {len(unique)} downloads failed", failures
            )
