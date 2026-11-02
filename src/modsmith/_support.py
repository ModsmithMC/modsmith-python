import errno
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path


def default_cache_dir() -> Path:
    return user_cache_path("modsmith", appauthor=False)


def slugify(name: str, fallback: str = "instance") -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or fallback


def copy_replace(source: Path, dest: Path) -> None:
    shutil.copy2(source, dest)
    source.unlink()


def replace_file(source: Path, dest: Path) -> None:
    """Rename over `dest`, copying when the filesystem refuses the rename.

    Containers such as MSIX can reject renames inside redirected folders with
    EXDEV even though both paths share a directory.
    """
    try:
        os.replace(source, dest)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        copy_replace(source, dest)


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    replace_file(temp, path)


def write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    write_atomic(path, text.encode("utf-8"))
