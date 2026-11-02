"""Build real archives and directory layouts for tests."""

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent.parent / "data"
PROFILE_FILES = sorted((DATA / "install_profiles").glob("*.json"))


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def write_zip(path: Path, files: dict[str, bytes | str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def write_mrpack(
    path: Path,
    files: list[dict[str, Any]] | tuple[()] = (),
    overrides: dict[str, bytes | str] | None = None,
    *,
    name: str = "Test",
    version: str = "1.0",
    loader: dict[str, str] | None = None,
) -> Path:
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "name": name,
        "versionId": version,
        "files": list(files),
        "dependencies": {
            "minecraft": "1.21.1",
            **(loader or {"fabric-loader": "0.16.10"}),
        },
    }
    content: dict[str, bytes | str] = {"modrinth.index.json": json.dumps(index)}
    content.update(overrides or {})
    return write_zip(path, content)


def mrpack_file(
    name: str, data: bytes, url: str, env: dict[str, str] | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": f"mods/{name}",
        "hashes": {"sha1": sha1(data)},
        "downloads": [url],
        "fileSize": len(data),
    }
    if env:
        entry["env"] = env
    return entry


def write_curseforge_pack(
    path: Path,
    manifest: dict[str, Any],
    overrides: dict[str, bytes | str] | None = None,
) -> Path:
    return write_zip(path, {"manifest.json": json.dumps(manifest), **(overrides or {})})


def link_directory(target: Path, link: Path) -> None:
    """Link a directory without needing symlink privileges on Windows."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def build_processor_jars(dest: Path, javac: str) -> tuple[Path, Path]:
    """Compile the test processor. `Tool` needs `Helper` on the classpath."""
    source = DATA / "processor"
    classes = dest / "classes"
    classes.mkdir(parents=True)
    subprocess.run(
        [
            javac,
            "--release",
            "11",
            "-d",
            str(classes),
            str(source / "Tool.java"),
            str(source / "Helper.java"),
        ],
        check=True,
        capture_output=True,
    )
    tool = write_zip(
        dest / "tool.jar",
        {
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nMain-Class: demo.Tool\n",
            "demo/Tool.class": (classes / "demo" / "Tool.class").read_bytes(),
        },
    )
    helper = write_zip(
        dest / "helper.jar",
        {"demo/Helper.class": (classes / "demo" / "Helper.class").read_bytes()},
    )
    return tool, helper


def jdk_home(java: str) -> Path:
    return Path(java).resolve().parent.parent
