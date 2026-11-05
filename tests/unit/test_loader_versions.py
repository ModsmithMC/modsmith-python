import pytest

from modsmith.loaders import Forge, LoaderVersion
from modsmith.loaders._base import is_stable, recommend, version_key
from modsmith.loaders._forge import neoforge_minecraft


@pytest.mark.parametrize(
    ("version", "minecraft"),
    [
        ("21.1.77", "1.21.1"),
        ("21.0.143", "1.21"),
        ("20.2.3-beta", "1.20.2"),
        ("26.1.2.125", "26.1.2"),
        ("26.3.0.100", "26.3"),
        ("21", None),
        ("21.x.1", None),
    ],
)
def test_neoforge_game_versions(version, minecraft):
    assert neoforge_minecraft(version) == minecraft


@pytest.mark.parametrize(
    ("version", "stable"),
    [
        ("0.16.10", True),
        ("0.20.0-beta.9", False),
        ("1.0-RC1", False),
        ("2.0-pre3", False),
    ],
)
def test_stability_from_the_version_text(version, stable):
    assert is_stable(version) is stable


def test_versions_sort_by_number_with_releases_after_their_pre_releases():
    ordered = sorted(["0.16.9", "0.16.10", "0.17.0-beta.1", "0.17.0"], key=version_key)
    assert ordered == ["0.16.9", "0.16.10", "0.17.0-beta.1", "0.17.0"]


def test_recommend_ignores_a_choice_that_is_not_listed():
    found = recommend([LoaderVersion("x", "1", "1.0")], choice="9")
    assert found[0].recommended


def test_recommend_marks_nothing_when_nothing_is_stable():
    found = recommend([LoaderVersion("x", "1-beta", "1.0", stable=False)])
    assert not found[0].recommended


@pytest.mark.parametrize("minecraft", ["1.12.1", "1.7.10", "1.8"])
def test_forge_offers_nothing_it_cannot_install(minecraft):
    # Answered before any request, so it works with the network blocked.
    assert Forge.available(minecraft) == []
