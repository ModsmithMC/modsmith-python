import hashlib
import json
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_FIXTURES = sorted((FIXTURES / "install_profiles").glob("*.json"))


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def write_jar(path: Path, main_class: str = "demo.Main") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", f"Main-Class: {main_class}\n")
    return path


def write_zip(path: Path, files: dict[str, bytes | str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def fake_runtime(root: Path, component: str) -> Path:
    path = root / component / "windows-x64" / component / "bin" / "java.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"java")
    return path


def mrpack(path: Path, files=(), overrides=None, name="Test", version="1.0", loader=None):
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "name": name,
        "versionId": version,
        "files": list(files),
        "dependencies": {"minecraft": "1.21.1", **(loader or {"fabric-loader": "0.16.10"})},
    }
    content: dict[str, bytes | str] = {"modrinth.index.json": json.dumps(index)}
    content.update(overrides or {})
    return write_zip(path, content)


def mrpack_file(name: str, data: bytes, url: str, env=None) -> dict:
    entry = {
        "path": f"mods/{name}",
        "hashes": {"sha1": sha1(data)},
        "downloads": [url],
        "fileSize": len(data),
    }
    if env:
        entry["env"] = env
    return entry
