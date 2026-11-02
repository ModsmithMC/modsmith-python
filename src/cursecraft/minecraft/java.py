import lzma
import os
import platform
import stat
import sys
from pathlib import Path

from ..core.download import Downloader, DownloadTask, file_hash
from ..core.errors import JavaNotFoundError
from ..core.events import Emit, Message, null_emit
from ..core.http import HttpClient

RUNTIME_INDEX_URL = "https://launchermeta.mojang.com/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
STORE_PACKAGE = "Microsoft.4297127D64EC6_8wekyb3d8bbwe"
COMPLETE_MARKER = ".cursecraft-complete"
JAVA_BINARIES = (
    "bin/java.exe",
    "bin/java",
    "jre.bundle/Contents/Home/bin/java",
)
PREFERRED_COMPONENTS = (
    "java-runtime-delta",
    "java-runtime-gamma",
    "java-runtime-beta",
    "java-runtime-epsilon",
    "java-runtime-alpha",
    "jre-legacy",
)


def platform_key() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        if arm:
            return "windows-arm64"
        return "windows-x64" if machine in ("amd64", "x86_64") else "windows-x86"
    if sys.platform == "darwin":
        return "mac-os-arm64" if arm else "mac-os"
    return "linux" if machine in ("amd64", "x86_64") else "linux-i386"


def official_runtime_dirs(minecraft_dir: Path) -> list[Path]:
    dirs = [minecraft_dir / "runtime"]
    if sys.platform == "win32":
        local = os.getenv("LOCALAPPDATA")
        if local:
            dirs.append(
                Path(local, "Packages", STORE_PACKAGE, "LocalCache", "Local", "runtime")
            )
        program_files = os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
        dirs.append(Path(program_files, "Minecraft Launcher", "runtime"))
    return dirs


def find_binary(runtime_dir: Path, component: str) -> Path | None:
    component_dir = runtime_dir / component
    if not component_dir.is_dir():
        return None
    for platform_dir in sorted(component_dir.iterdir()):
        for binary in JAVA_BINARIES:
            path = platform_dir / component / binary
            if path.is_file():
                return path
    return None


class JavaResolver:
    def __init__(
        self,
        http: HttpClient,
        downloader: Downloader,
        minecraft_dir: Path,
        cache_dir: Path,
    ) -> None:
        self.http = http
        self.downloader = downloader
        self.official_dirs = official_runtime_dirs(minecraft_dir)
        self.cache_runtime_dir = cache_dir / "java"

    def _cached(self, component: str) -> Path | None:
        if not (self.cache_runtime_dir / component / COMPLETE_MARKER).is_file():
            return None
        return find_binary(self.cache_runtime_dir, component)

    def find(self, component: str) -> Path | None:
        for runtime_dir in self.official_dirs:
            binary = find_binary(runtime_dir, component)
            if binary:
                return binary
        return self._cached(component)

    def candidates(self, component: str) -> list[Path]:
        exact = self.find(component)
        if exact:
            return [exact]
        found = (self.find(name) for name in PREFERRED_COMPONENTS)
        return [binary for binary in found if binary]

    def download(self, component: str, emit: Emit = null_emit) -> Path:
        index = self.http.get_json(RUNTIME_INDEX_URL)
        entries = index.get(platform_key(), {}).get(component) or []
        if not entries:
            raise JavaNotFoundError(
                f"Mojang provides no {component} runtime for {platform_key()}"
            )
        manifest = self.http.get_json(entries[0]["manifest"]["url"])
        target = self.cache_runtime_dir / component / platform_key() / component

        tasks: list[DownloadTask] = []
        pending: list[tuple[Path, Path, str]] = []
        links: list[tuple[Path, str]] = []
        executables: list[Path] = []
        for name, entry in manifest["files"].items():
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
                    tasks.append(DownloadTask(compressed["url"], packed, compressed["sha1"]))
                    pending.append((packed, path, raw["sha1"]))
                else:
                    tasks.append(DownloadTask(raw["url"], path, raw["sha1"]))

        self.downloader.fetch_all(tasks, emit, f"Downloading {component}")
        for packed, path, sha1 in pending:
            with lzma.open(packed) as source, open(path, "wb") as dest:
                while chunk := source.read(1 << 20):
                    dest.write(chunk)
            packed.unlink()
            if file_hash(path) != sha1:
                path.unlink()
                raise JavaNotFoundError(f"Corrupt Java runtime file: {path.name}")
        for path in executables:
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        for path, link_target in links:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            path.symlink_to(link_target)

        (self.cache_runtime_dir / component / COMPLETE_MARKER).touch()
        binary = self._cached(component)
        if binary is None:
            raise JavaNotFoundError(f"No java binary found in {component}")
        emit(Message(f"Installed Java runtime {component}"))
        return binary
