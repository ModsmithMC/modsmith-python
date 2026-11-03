"""Read the real version lists of every built-in loader."""

import pytest

import modsmith as ms

CASES = [
    ("fabric", "1.21.1"),
    ("quilt", "1.21.1"),
    ("forge", "1.20.1"),
    ("neoforge", "1.21.1"),
    ("neoforge", "1.20.1"),
]


@pytest.mark.parametrize(("kind", "minecraft"), CASES)
def test_every_loader_lists_versions_and_recommends_one(kind, minecraft):
    found = ms.loaders.versions(kind, minecraft)
    assert found
    assert all(item.minecraft == minecraft for item in found)
    assert sum(item.recommended for item in found) == 1
    loader = ms.loaders.recommended(kind, minecraft)
    assert loader.kind == kind
    assert loader.minecraft == minecraft


def test_forge_recommends_what_forge_recommends():
    found = ms.loaders.versions("forge", "1.20.1")
    assert any(item.recommended and item.stable for item in found)


def test_unknown_game_versions_have_no_loader_versions():
    assert ms.loaders.versions("fabric", "0.0.1") == []
