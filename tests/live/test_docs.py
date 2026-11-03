"""Run the documentation's examples against the real services."""

import os

import pytest

from tests.lib.docs import prepare, run_page

PAGES = [
    "get-started/quickstart.md",
    "guides/dependencies.md",
    "guides/loaders.md",
    "guides/java.md",
    "guides/errors.md",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_runs(page, tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    run_page(page)


@pytest.mark.skipif(
    not os.getenv("CURSEFORGE_API_KEY"), reason="CURSEFORGE_API_KEY is not set"
)
def test_platforms_page_runs(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    run_page("guides/platforms.md")
