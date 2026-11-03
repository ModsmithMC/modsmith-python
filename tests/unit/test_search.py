import pytest

from modsmith.platforms import Project
from modsmith.platforms._base import category_names, collect_pages, release_versions
from tests.lib.catalog import Catalog, release


def numbered(count: int) -> list[Project]:
    return [
        Project("test", str(index), str(index), str(index)) for index in range(count)
    ]


class Pages:
    """A source of numbered results that records each page it serves."""

    def __init__(self, total: int) -> None:
        self.all = numbered(total)
        self.requests: list[tuple[int, int]] = []

    def __call__(self, start: int, size: int) -> tuple[list[Project], int]:
        self.requests.append((start, size))
        return self.all[start : start + size], len(self.all)


def test_one_page_is_enough_for_a_small_limit():
    pages = Pages(500)
    results = collect_pages(pages, 0, 20, 100)
    assert [item.id for item in results.projects] == [str(index) for index in range(20)]
    assert results.total == 500
    assert pages.requests == [(0, 20)]


def test_large_limits_read_several_pages():
    pages = Pages(500)
    results = collect_pages(pages, 10, 120, 50)
    assert len(results.projects) == 120
    assert results.projects[0].id == "10"
    assert results.offset == 10
    assert pages.requests == [(10, 50), (60, 50), (110, 20)]


def test_reading_stops_at_the_end():
    pages = Pages(70)
    results = collect_pages(pages, 0, 200, 50)
    assert len(results.projects) == 70
    assert pages.requests == [(0, 50), (50, 50)]


def test_reading_stops_where_the_platform_stops():
    pages = Pages(500)
    results = collect_pages(pages, 90, 50, 50, reachable=100)
    assert len(results.projects) == 10
    assert pages.requests == [(90, 10)]
    assert collect_pages(pages, 100, 50, 50, reachable=100).projects == ()


def test_release_versions():
    labels = ["1.20.1", "26.3-rc-1", "1.21.1", "1.21", "26.3", "1.21.1", "Fabric"]
    assert release_versions(labels) == ("26.3", "1.21.1", "1.21", "1.20.1")


def test_category_names():
    assert category_names(["game-mechanics", "fabric", "optimization"], {"fabric"}) == (
        "Game Mechanics",
        "Optimization",
    )


def test_bulk_lookup_falls_back_to_single_lookups():
    catalog = Catalog(release("a"), release("b"))
    found = catalog.get_projects(["a", "b", "missing", "a"])
    assert sorted(found) == ["a", "b"]
    assert found["a"].id == "a"


@pytest.mark.parametrize(
    "sort", ["relevance", "downloads", "popularity", "newest", "updated"]
)
def test_both_platforms_know_every_sort(sort):
    from modsmith.platforms._curseforge import SORT_FIELDS
    from modsmith.platforms._modrinth import SORT_INDEXES

    assert sort in SORT_FIELDS
    assert sort in SORT_INDEXES


def test_authors_default_to_the_projects_own():
    catalog = Catalog()
    named = Project("modrinth", "a", "a", "A", author="Someone")
    assert catalog.authors(named) == ("Someone",)
    assert catalog.authors(Project("modrinth", "b", "b", "B")) == ()
