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
    create,
    parse,
    register,
)


@pytest.mark.parametrize(
    ("loader_id", "minecraft", "expected"),
    [
        ("forge-47.3.0", "1.20.1", Forge("47.3.0", "1.20.1")),
        ("neoforge-21.1.233", "1.21.1", NeoForge("21.1.233", "1.21.1")),
        ("neoforge-1.20.1-47.1.106", "1.20.1", NeoForge("47.1.106", "1.20.1")),
        ("fabric-0.16.10", "1.21.1", Fabric("0.16.10", "1.21.1")),
        ("quilt-0.26.0", "1.21.1", Quilt("0.26.0", "1.21.1")),
    ],
)
def test_parse_loader_id(loader_id, minecraft, expected):
    assert parse(loader_id, minecraft) == expected


def test_create_accepts_modrinth_names():
    assert create("fabric-loader", "1", "1.21") == Fabric("1", "1.21")
    assert create("quilt-loader", "1", "1.21") == Quilt("1", "1.21")


@pytest.mark.parametrize("loader_id", ["forge", "liteloader-1"])
def test_parse_rejects_unsupported(loader_id):
    with pytest.raises(UnsupportedError):
        parse(loader_id, "1.20.1")


def test_third_party_loader_can_register():
    @register
    @dataclass(frozen=True)
    class Custom(Loader):
        kind: ClassVar[str] = "custom"

        def version_id(self, *, session=None, cache_dir=None):
            return "custom-1"

        def install(self, game, **kwargs):
            return "custom-1"

    assert isinstance(create("custom", "1", "1.21"), Custom)


@pytest.mark.parametrize(
    ("loader", "url"),
    [
        (
            Forge("47.3.0", "1.20.1", "https://forge.test"),
            "https://forge.test/net/minecraftforge/forge/1.20.1-47.3.0/forge-1.20.1-47.3.0-installer.jar",
        ),
        (
            NeoForge("21.1.233", "1.21.1", "https://neo.test/releases"),
            "https://neo.test/releases/net/neoforged/neoforge/21.1.233/neoforge-21.1.233-installer.jar",
        ),
        (
            NeoForge("47.1.106", "1.20.1", "https://neo.test/releases"),
            "https://neo.test/releases/net/neoforged/forge/1.20.1-47.1.106/forge-1.20.1-47.1.106-installer.jar",
        ),
    ],
)
def test_installer_urls(loader, url):
    assert loader.installer_url() == url
