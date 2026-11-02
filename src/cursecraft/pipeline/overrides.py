import hashlib
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..core.download import file_hash
from ..core.errors import SourceError


@dataclass
class OverrideResult:
    hashes: dict[str, str] = field(default_factory=dict)
    kept: list[str] = field(default_factory=list)


def safe_relative(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name:
        raise SourceError(f"Unsafe path in modpack: {name}")
    return path.as_posix()


def write_atomic(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, dest)


def apply_overrides(
    archive_path: Path,
    prefix: str,
    game_dir: Path,
    previous: dict[str, str] | None = None,
) -> OverrideResult:
    is_update = previous is not None
    previous = previous or {}
    result = OverrideResult()
    root = prefix.strip("/") + "/"
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(root):
                continue
            relative = safe_relative(info.filename.removeprefix(root))
            data = archive.read(info)
            pack_hash = hashlib.sha1(data).hexdigest()
            result.hashes[relative] = pack_hash
            dest = game_dir / relative
            if dest.is_file():
                current = file_hash(dest)
                if current == pack_hash:
                    continue
                if is_update and current != previous.get(relative):
                    result.kept.append(relative)
                    continue
            write_atomic(dest, data)
    return result


def remove_stale(
    game_dir: Path, previous: dict[str, str], current: dict[str, str]
) -> list[str]:
    removed: list[str] = []
    for relative, expected in previous.items():
        path = game_dir / relative
        if relative in current or not path.is_file():
            continue
        if file_hash(path) == expected:
            path.unlink()
            removed.append(relative)
    return removed
