import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from cursecraft.core.download import Downloader
from cursecraft.core.http import HttpClient
from cursecraft.core.paths import maven_path
from cursecraft.loaders.base import InstallContext
from cursecraft.minecraft.java import JavaResolver
from cursecraft.minecraft.versions import VersionService

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_FIXTURES = sorted((FIXTURES / "install_profiles").glob("*.json"))


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def write_jar(path: Path, main_class: str = "demo.Main") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", f"Main-Class: {main_class}\n")
    return path


def write_installer(path: Path, profile: dict, version: dict, files: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("install_profile.json", json.dumps(profile))
        archive.writestr("version.json", json.dumps(version))
        for name, data in (files or {}).items():
            archive.writestr(name, data)
    return path


def fake_java(root: Path, component: str, platform: str = "windows-x64") -> Path:
    path = root / component / platform / component / "bin" / "java.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"java")
    return path


def library_path(root: Path, coord: str) -> Path:
    return root / "libraries" / maven_path(coord)


class FakeRunner:
    def __init__(self, on_run=None, returncode: int = 0, stdout: str = "") -> None:
        self.on_run = on_run
        self.returncode = returncode
        self.stdout = stdout
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.kwargs.append(kwargs)
        if self.on_run:
            self.on_run(command)
        return subprocess.CompletedProcess(command, self.returncode, self.stdout)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    root = tmp_path / "minecraft"
    root.mkdir()
    http = HttpClient(backoff=0)
    downloader = Downloader(http, max_workers=2)
    return InstallContext(
        root=root,
        cache_dir=tmp_path / "cache",
        http=http,
        downloader=downloader,
        versions=VersionService(http, downloader, root),
        java=JavaResolver(http, downloader, root, tmp_path / "cache"),
    )
