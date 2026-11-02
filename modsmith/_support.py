"""Internal helpers for files and names."""

import errno
import json
import os
import re
import shutil
from pathlib import Path
from typing import IO, Any

from platformdirs import user_cache_path


def default_cache_dir() -> Path:
    """Return the per-user directory used for caches by default."""
    return user_cache_path("modsmith", appauthor=False)


def slugify(name: str, fallback: str = "instance") -> str:
    """Turn a display name into a lowercase, hyphenated slug.

    Args:
        name: The display name.
        fallback: Returned when ``name`` has no ASCII letters or digits.

    Returns:
        The slug.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or fallback


def copy_replace(source: Path, dest: Path) -> None:
    """Copy ``source`` over ``dest``, then delete ``source``."""
    shutil.copy2(source, dest)
    source.unlink()


def replace_file(source: Path, dest: Path) -> None:
    """Rename over ``dest``, copying when the filesystem refuses the rename.

    Containers such as MSIX can reject renames inside redirected folders with
    ``EXDEV`` even though both paths share a directory.

    Args:
        source: The file to move.
        dest: The file to replace.

    Raises:
        OSError: The rename failed for another reason, or the copy failed.
    """
    try:
        os.replace(source, dest)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        copy_replace(source, dest)


def write_atomic(path: Path, data: bytes | IO[bytes]) -> None:
    """Write a file through a temporary sibling, creating parent directories.

    Readers see either the old contents or the new ones, never a partial file.

    Args:
        path: The file to write.
        data: The contents, or an open file to copy them from.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "wb") as file:
        if isinstance(data, bytes):
            file.write(data)
        else:
            shutil.copyfileobj(data, file)
    replace_file(temp, path)


def write_json(path: Path, data: Any) -> None:
    """Atomically write indented JSON as UTF-8."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    write_atomic(path, text.encode("utf-8"))
