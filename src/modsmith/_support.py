import json
import os
import re
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path


def default_cache_dir() -> Path:
    return user_cache_path("modsmith", appauthor=False)


def slugify(name: str, fallback: str = "instance") -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or fallback


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    write_atomic(path, text.encode("utf-8"))
