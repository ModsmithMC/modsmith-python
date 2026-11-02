"""The documentation's examples compile, name real objects and run offline."""

import re

import pytest

import modsmith
from tests.lib.docs import DOCS, pages, prepare, python_blocks, run_page

NAME = re.compile(r"(?<![\w./-])(?:ms|modsmith)((?:\.[A-Za-z_]\w*)+)")
OFFLINE_PAGES = [
    "guides/modpacks.md",
    "guides/instances.md",
    "guides/launcher.md",
    "guides/progress.md",
    "guides/extending.md",
]


def page_id(page):
    return page.relative_to(DOCS).as_posix()


@pytest.mark.parametrize("page", pages(), ids=page_id)
def test_examples_compile(page):
    for block in python_blocks(page):
        compile(block, str(page), "exec")


@pytest.mark.parametrize("page", pages(), ids=page_id)
def test_named_objects_exist(page):
    for match in NAME.finditer(page.read_text(encoding="utf-8")):
        target = modsmith
        for part in match[1].removeprefix(".").split("."):
            target = getattr(target, part)


def test_guides_are_in_the_navigation():
    index = (DOCS / "guides" / "index.md").read_text(encoding="utf-8")
    guides = (DOCS / "guides").glob("*.md")
    assert all(guide.stem in index for guide in guides if guide.stem != "index")


@pytest.mark.parametrize("page", OFFLINE_PAGES)
def test_offline_pages_run(page, tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    run_page(page)
