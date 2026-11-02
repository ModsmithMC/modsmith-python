import pytest

from modsmith.minecraft import MavenCoord, maven_path


@pytest.mark.parametrize(
    ("coord", "path"),
    [
        ("net.minecraft:client:1.21", "net/minecraft/client/1.21/client-1.21.jar"),
        (
            "net.minecraftforge:forge:1.21-52:shim",
            "net/minecraftforge/forge/1.21-52/forge-1.21-52-shim.jar",
        ),
        (
            "de.oceanlabs:mcp:1.21:mappings@tsrg",
            "de/oceanlabs/mcp/1.21/mcp-1.21-mappings.tsrg",
        ),
        ("a.b:c:1@zip", "a/b/c/1/c-1.zip"),
    ],
)
def test_maven_path(coord, path):
    assert maven_path(coord) == path


@pytest.mark.parametrize("coord", ["a:b", "a:b:c:d:e", "a:b:c@d@e"])
def test_invalid_coordinates(coord):
    with pytest.raises(ValueError, match="Invalid maven"):
        MavenCoord.parse(coord)
