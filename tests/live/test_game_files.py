"""Real Mojang downloads and complete loader installs, processors included."""

import pytest

import modsmith as ms

FORGE_LIKE = [
    ms.loaders.Forge("25.0.223", "1.13.2"),
    ms.loaders.Forge("36.2.42", "1.16.5"),
    ms.loaders.Forge("47.3.0", "1.20.1"),
    ms.loaders.Forge("52.0.40", "1.21.1"),
    ms.loaders.Forge("66.1.0", "26.3"),
    ms.loaders.NeoForge("47.1.106", "1.20.1"),
    ms.loaders.NeoForge("21.1.233", "1.21.1"),
    ms.loaders.NeoForge("26.3.0.101", "26.3"),
]
META = [
    ms.loaders.Fabric("0.20.1", "1.14"),
    ms.loaders.Fabric("0.16.10", "1.21.1"),
    ms.loaders.Fabric("0.20.1", "26.3"),
    ms.loaders.Quilt("0.30.2", "1.14.4"),
    ms.loaders.Quilt("0.30.2", "1.21.1"),
    ms.loaders.Quilt("0.30.2", "26.3"),
]


def loader_id(loader):
    return f"{loader.kind}-{loader.minecraft}"


def assert_libraries_present(game, version_id):
    for item in game.version(version_id).raw.get("libraries", []):
        artifact = (item.get("downloads") or {}).get("artifact") or {}
        path = artifact.get("path") or ms.minecraft.maven_path(item["name"])
        assert (game.libraries_dir / path).is_file(), path


def test_version_manifest():
    versions = ms.minecraft.list_versions()
    assert any(item.id == "1.21.1" for item in versions)


@pytest.mark.parametrize("loader", META, ids=loader_id)
def test_install_meta_loader(tmp_path, loader):
    game = ms.minecraft.GameDir(tmp_path)
    version_id = loader.install(game)
    assert game.has_version(version_id)
    assert_libraries_present(game, version_id)


@pytest.mark.parametrize("loader", FORGE_LIKE, ids=loader_id)
def test_install_processor_loader(tmp_path, loader):
    game = ms.minecraft.GameDir(tmp_path / "minecraft")
    version_id = loader.install(game, cache_dir=tmp_path / "cache")
    assert game.has_version(version_id)
    assert_libraries_present(game, version_id)


def test_download_java_runtime(tmp_path):
    runtime = ms.java.download("java-runtime-epsilon", cache_dir=tmp_path)
    assert runtime.executable.is_file()
    assert ms.java.find("java-runtime-epsilon", cache_dir=tmp_path) == runtime
