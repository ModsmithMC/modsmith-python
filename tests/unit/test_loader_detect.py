"""Recognising loaders in version JSONs shaped like the ones installers write."""

from dataclasses import dataclass
from typing import ClassVar

import pytest

from modsmith.errors import UnsupportedError
from modsmith.loaders import (
    Fabric,
    Forge,
    Loader,
    NeoForge,
    Quilt,
    detect,
    register,
)
from modsmith.minecraft import GameDir


@pytest.fixture
def game(tmp_path) -> GameDir:
    folder = GameDir(tmp_path)
    for version in ("1.13.2", "1.20.1", "1.21.1"):
        folder.write_version(version, {"id": version, "libraries": []})
    return folder


def child(game, version_id, parent, **fields):
    game.write_version(version_id, {"id": version_id, "inheritsFrom": parent, **fields})
    return version_id


def libraries(*names):
    return [{"name": name} for name in names]


def test_vanilla_has_no_loader(game):
    assert detect(game, "1.21.1") is None


def test_fabric_and_quilt_by_their_library(game):
    fabric = child(
        game,
        "fabric-loader-0.16.10-1.21.1",
        "1.21.1",
        libraries=libraries(
            "org.ow2.asm:asm:9.7", "net.fabricmc:fabric-loader:0.16.10"
        ),
    )
    quilt = child(
        game,
        "quilt-loader-0.30.2-1.21.1",
        "1.21.1",
        libraries=libraries("org.quiltmc:quilt-loader:0.30.2", "odd", 7),
    )
    assert detect(game, fabric) == Fabric("0.16.10", "1.21.1")
    assert detect(game, quilt) == Quilt("0.30.2", "1.21.1")


def test_forge_by_its_argument(game):
    version = child(
        game,
        "1.20.1-forge-47.3.0",
        "1.20.1",
        arguments={
            "game": [
                "--launchTarget",
                "forgeclient",
                "--fml.forgeVersion",
                "47.3.0",
                {"rules": [], "value": "x"},
            ]
        },
        libraries=libraries("net.minecraftforge:fmlloader:1.20.1-47.3.0"),
    )
    assert detect(game, version) == Forge("47.3.0", "1.20.1")


def test_old_forge_by_its_library(game):
    version = child(
        game,
        "1.13.2-forge-25.0.223",
        "1.13.2",
        libraries=libraries("net.minecraftforge:forge:1.13.2-25.0.223"),
    )
    assert detect(game, version) == Forge("25.0.223", "1.13.2")


def test_neoforge(game):
    version = child(
        game,
        "neoforge-21.1.233",
        "1.21.1",
        arguments={
            "game": ["--fml.neoForgeVersion", "21.1.233", "--fml.fmlVersion", "4.0.42"]
        },
        libraries=libraries("net.neoforged.fancymodloader:loader:4.0.42"),
    )
    assert detect(game, version) == NeoForge("21.1.233", "1.21.1")


def test_neoforge_for_1_20_1_passes_forges_argument(game):
    version = child(
        game,
        "1.20.1-forge-47.1.106",
        "1.20.1",
        arguments={"game": ["--fml.forgeVersion", "47.1.106"]},
        libraries=libraries("net.neoforged:forge:1.20.1-47.1.106:universal"),
    )
    assert detect(game, version) == NeoForge("47.1.106", "1.20.1")


def test_legacy_arguments(game):
    version = child(
        game,
        "legacy",
        "1.13.2",
        minecraftArguments="--username x --fml.forgeVersion 25.0.223",
    )
    assert detect(game, version) == Forge("25.0.223", "1.13.2")


def test_a_version_over_a_loader_version(game):
    loader = child(
        game,
        "fabric-loader-0.16.10-1.21.1",
        "1.21.1",
        libraries=libraries("net.fabricmc:fabric-loader:0.16.10"),
    )
    tweaked = child(game, "my-tweaks", loader)
    assert detect(game, tweaked) == Fabric("0.16.10", "1.21.1")


def test_a_missing_version(game):
    child(game, "orphan", "1.7.10")
    with pytest.raises(UnsupportedError):
        detect(game, "orphan")
    with pytest.raises(UnsupportedError):
        detect(game, "nothing")


def test_third_party_loaders_take_part(game):
    @register
    @dataclass(frozen=True)
    class Marked(Loader):
        kind: ClassVar[str] = "marked-loader"

        def version_id(self, *, session=None, cache_dir=None):
            return "marked"

        def install(self, game, **options):
            return "marked"

        @classmethod
        def from_version(cls, version, minecraft):
            mark = version.raw.get("mark")
            return cls(mark, minecraft) if mark else None

    version = child(game, "marked", "1.21.1", mark="3")
    assert detect(game, version) == Marked("3", "1.21.1")
