"""Run the code examples in the documentation."""

import re
from pathlib import Path

import pytest

import modsmith as ms
from tests.lib.builders import write_mrpack

DOCS = Path(__file__).parents[2] / "docs"
BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)
# Examples that depend on something a test cannot provide.
UNAVAILABLE = ("pack.zip", "/usr/lib/jvm")


def pages() -> list[Path]:
    return sorted(path for path in DOCS.rglob("*.md") if "_build" not in path.parts)


def python_blocks(page: Path) -> list[str]:
    return BLOCK.findall(page.read_text(encoding="utf-8"))


def prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the examples a modpack, a working directory and a launcher to use."""
    for name in ("APPDATA", "HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    write_mrpack(tmp_path / "pack.mrpack", overrides={"overrides/config/a.txt": "a"})
    game = ms.minecraft.GameDir.default().path
    game.mkdir(parents=True)
    (game / "launcher_profiles.json").write_text('{"profiles": {}}', encoding="utf-8")


def run_page(relative: str) -> None:
    """Run a page's examples in order, as a reader would."""
    namespace: dict[str, object] = {}
    for block in python_blocks(DOCS / relative):
        if not any(marker in block for marker in UNAVAILABLE):
            exec(compile(block, relative, "exec"), namespace)
