from modsmith.platforms._curseforge import split_versions


def test_game_versions_and_loaders_are_separated():
    labels = ["Client", "Fabric", "1.21.1", "Server", "26.3", "NeoForge", "Beta 1.7.3"]
    assert split_versions(labels) == (("1.21.1", "26.3"), ("fabric", "neoforge"))


def test_unknown_loaders_and_repeats_are_dropped():
    labels = ["Forge", "Risugami's ModLoader", "forge", "1.12.2"]
    assert split_versions(labels) == (("1.12.2",), ("forge",))
