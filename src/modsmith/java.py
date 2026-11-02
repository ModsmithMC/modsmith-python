"""Find Java runtimes from the official launcher, or download Mojang's."""

import lzma
import os
import platform
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._support import default_cache_dir
from .errors import JavaError
from .minecraft import GameDir, Version
from .net import Resource, Session, file_hash
from .net import download as fetch
from .net._session import session_scope
from .progress import CancelToken, ProgressCallback

__all__ = [
    "JavaRuntime",
    "download",
    "find",
    "find_all",
    "official_runtime_dirs",
    "platform_key",
    "required_for",
]

RUNTIME_INDEX_URL = "https://launchermeta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
STORE_PACKAGE = "Microsoft.4297127D64EC6_8wekyb3d8bbwe"
LEGACY_COMPONENT = "jre-legacy"
COMPLETE_MARKER = ".modsmith-complete"
JAVA_BINARIES = ("bin/java.exe", "bin/java", "jre.bundle/Contents/Home/bin/java")
PREFERRED_COMPONENTS = (
    "java-runtime-delta",
    "java-runtime-gamma",
    "java-runtime-beta",
    "java-runtime-epsilon",
    "java-runtime-alpha",
    LEGACY_COMPONENT,
)


@dataclass(frozen=True)
class JavaRuntime:
    component: str
    executable: Path


def platform_key() -> str:
    """Mojang's name for the current platform, such as `windows-x64`."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        if arm:
            return "windows-arm64"
        return "windows-x64" if machine in ("amd64", "x86_64") else "windows-x86"
    if sys.platform == "darwin":
        return "mac-os-arm64" if arm else "mac-os"
    return "linux" if machine in ("amd64", "x86_64") else "linux-i386"


def official_runtime_dirs(game: GameDir | None = None) -> list[Path]:
    """Directories where the official launcher keeps Java runtimes."""
    game = game or GameDir.default()
    dirs = [game.path / "runtime"]
    if sys.platform == "win32":
        local = os.getenv("LOCALAPPDATA")
        if local:
            dirs.append(
                Path(local, "Packages", STORE_PACKAGE, "LocalCache", "Local", "runtime")
            )
        program_files = os.getenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        dirs.append(Path(program_files, "Minecraft Launcher", "runtime"))
    return dirs


def required_for(version: Version, game: GameDir | None = None) -> str:
    """The runtime component a version needs, following `inheritsFrom`."""
    current = version
    while current.java_component is None and current.inherits_from and game:
        current = game.version(current.inherits_from)
    return current.java_component or LEGACY_COMPONENT


def _binary_in(runtime_dir: Path, component: str) -> Path | None:
    component_dir = runtime_dir / component
    if not component_dir.is_dir():
        return None
    for platform_dir in sorted(component_dir.iterdir()):
        for binary in JAVA_BINARIES:
            path = platform_dir / component / binary
            if path.is_file():
                return path
    return None


def _runtime_cache(cache_dir: Path | None) -> Path:
    return (cache_dir or default_cache_dir()) / "java"


def find(
    component: str,
    *,
    game: GameDir | None = None,
    cache_dir: Path | None = None,
) -> JavaRuntime | None:
    """Find a runtime in the official launcher or the download cache."""
    for runtime_dir in official_runtime_dirs(game):
        binary = _binary_in(runtime_dir, component)
        if binary:
            return JavaRuntime(component, binary)
    cache = _runtime_cache(cache_dir)
    if (cache / component / COMPLETE_MARKER).is_file():
        binary = _binary_in(cache, component)
        if binary:
            return JavaRuntime(component, binary)
    return None


def find_all(
    *, game: GameDir | None = None, cache_dir: Path | None = None
) -> list[JavaRuntime]:
    found = (find(c, game=game, cache_dir=cache_dir) for c in PREFERRED_COMPONENTS)
    return [runtime for runtime in found if runtime]


def _unpack(packed: Path, path: Path, sha1: str, cancel: CancelToken | None) -> None:
    with lzma.open(packed) as source, open(path, "wb") as dest:
        while chunk := source.read(1 << 20):
            if cancel is not None:
                cancel.check()
            dest.write(chunk)
    packed.unlink()
    if file_hash(path) != sha1:
        path.unlink()
        raise JavaError(f"Corrupt Java runtime file: {path.name}")


def _install_entries(
    entries: dict[str, Any],
    target: Path,
    session: Session,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> None:
    resources: list[Resource] = []
    packed_files: list[tuple[Path, Path, str]] = []
    links: list[tuple[Path, str]] = []
    executables: list[Path] = []
    for name, entry in entries.items():
        path = target / name
        kind = entry["type"]
        if kind == "directory":
            path.mkdir(parents=True, exist_ok=True)
        elif kind == "link":
            links.append((path, entry["target"]))
        elif kind == "file":
            raw = entry["downloads"]["raw"]
            compressed = entry["downloads"].get("lzma")
            if entry.get("executable"):
                executables.append(path)
            if path.is_file() and file_hash(path) == raw["sha1"]:
                continue
            if compressed:
                packed = path.with_name(path.name + ".lzma")
                resources.append(
                    Resource.of(
                        compressed["url"],
                        packed,
                        {"sha1": compressed["sha1"]},
                        compressed.get("size"),
                    )
                )
                packed_files.append((packed, path, raw["sha1"]))
            else:
                resources.append(
                    Resource.of(
                        raw["url"], path, {"sha1": raw["sha1"]}, raw.get("size")
                    )
                )

    fetch(resources, session=session, progress=progress, cancel=cancel, task="java")
    for packed, path, sha1 in packed_files:
        _unpack(packed, path, sha1, cancel)
    for path in executables:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    for path, link_target in links:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        path.symlink_to(link_target)


def download(
    component: str,
    *,
    cache_dir: Path | None = None,
    session: Session | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    index_url: str = RUNTIME_INDEX_URL,
) -> JavaRuntime:
    """Download a Mojang runtime into the cache, never the launcher's directory."""
    cache = _runtime_cache(cache_dir)
    with session_scope(session) as client:
        index = client.get_json(index_url)
        builds: dict[str, Any] = index.get(platform_key(), {})
        entries: list[dict[str, Any]] = builds.get(component) or []
        if not entries:
            raise JavaError(f"Mojang has no {component} for {platform_key()}")
        manifest = client.get_json(entries[0]["manifest"]["url"])
        target = cache / component / platform_key() / component
        _install_entries(manifest["files"], target, client, progress, cancel)

    (cache / component / COMPLETE_MARKER).touch()
    binary = _binary_in(cache, component)
    if binary is None:
        raise JavaError(f"No java executable found in {component}")
    return JavaRuntime(component, binary)
