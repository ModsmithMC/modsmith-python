import json

import pytest

import modsmith as ms
from modsmith.metadata import Metadata, read
from tests.lib.builders import write_zip

PNG = b"\x89PNG icon"


def test_fabric_mod(tmp_path):
    info = {
        "id": "sodium",
        "name": "Sodium",
        "version": "0.6.0",
        "description": "Fast",
        "authors": ["JellySquid", {"name": "IMS"}],
        "icon": {"16": "small.png", "128": "assets/icon.png"},
    }
    jar = write_zip(
        tmp_path / "sodium.jar",
        {"fabric.mod.json": json.dumps(info), "assets/icon.png": PNG},
    )
    meta = read(jar)
    assert meta == Metadata(
        kind="mod",
        name="Sodium",
        id="sodium",
        version="0.6.0",
        description="Fast",
        authors=("JellySquid", "IMS"),
        loaders=("fabric",),
    )
    assert meta.icon == PNG


def test_fabric_json_may_hold_raw_newlines(tmp_path):
    jar = write_zip(
        tmp_path / "a.jar",
        {"fabric.mod.json": '{"id": "a", "description": "two\nlines"}'},
    )
    meta = read(jar)
    assert (meta.name, meta.description) == ("a", "two\nlines")


def test_quilt_mod(tmp_path):
    info = {
        "quilt_loader": {
            "id": "q",
            "version": "1.0",
            "metadata": {
                "name": "Q",
                "contributors": {"Ann": "Owner"},
                "icon": "icon.png",
            },
        }
    }
    jar = write_zip(
        tmp_path / "q.jar", {"quilt.mod.json": json.dumps(info), "icon.png": PNG}
    )
    meta = read(jar)
    assert (meta.id, meta.name, meta.version, meta.authors, meta.loaders) == (
        "q",
        "Q",
        "1.0",
        ("Ann",),
        ("quilt",),
    )
    assert meta.icon == PNG


MODS_TOML = """
modLoader = "javafml"
logoFile = "logo.png"
[[mods]]
modId = "create"
version = "${file.jarVersion}"
displayName = "Create"
authors = "simibubi, Kryppers"
description = '''
Building tools
'''
[[dependencies.create]]
modId = "%s"
mandatory = true
"""


def test_forge_mod_reads_its_version_from_the_manifest(tmp_path):
    jar = write_zip(
        tmp_path / "create.jar",
        {
            "META-INF/mods.toml": MODS_TOML % "forge",
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 0.5.1\n",
            "logo.png": PNG,
        },
    )
    meta = read(jar)
    assert (meta.id, meta.name, meta.version, meta.description) == (
        "create",
        "Create",
        "0.5.1",
        "Building tools",
    )
    assert meta.authors == ("simibubi", "Kryppers")
    assert meta.loaders == ("forge",)
    assert meta.icon == PNG


def test_early_neoforge_mods_use_the_forge_file_name(tmp_path):
    jar = write_zip(tmp_path / "n.jar", {"META-INF/mods.toml": MODS_TOML % "neoforge"})
    assert read(jar).loaders == ("neoforge",)


def test_neoforge_mod(tmp_path):
    jar = write_zip(
        tmp_path / "n.jar", {"META-INF/neoforge.mods.toml": MODS_TOML % "neoforge"}
    )
    meta = read(jar)
    assert meta.loaders == ("neoforge",)
    assert meta.version is None


@pytest.mark.parametrize(
    "wrap",
    [lambda mods: mods, lambda mods: {"modList": mods}],
    ids=["list", "mod-list"],
)
def test_legacy_forge_mod(tmp_path, wrap):
    mods = [{"modid": "old", "name": "Old", "version": "1", "authorList": ["X"]}]
    jar = write_zip(tmp_path / "old.jar", {"mcmod.info": json.dumps(wrap(mods))})
    meta = read(jar)
    assert (meta.id, meta.name, meta.authors, meta.loaders) == (
        "old",
        "Old",
        ("X",),
        ("forge",),
    )


def test_jar_for_several_loaders(tmp_path):
    jar = write_zip(
        tmp_path / "multi.jar",
        {
            "fabric.mod.json": json.dumps({"id": "m", "name": "Multi"}),
            "META-INF/neoforge.mods.toml": MODS_TOML % "neoforge",
        },
    )
    meta = read(jar)
    assert meta.name == "Multi"
    assert meta.loaders == ("fabric", "neoforge")
    assert meta.runs_on("fabric")
    assert meta.runs_on("neoforge")
    assert not meta.runs_on("forge")


def test_a_broken_declaration_falls_back_to_another(tmp_path):
    jar = write_zip(
        tmp_path / "m.jar",
        {"fabric.mod.json": "{not json", "META-INF/mods.toml": MODS_TOML % "forge"},
    )
    assert read(jar).loaders == ("forge",)


def test_resource_pack(tmp_path):
    mcmeta = {
        "pack": {
            "pack_format": 34,
            "description": [{"text": "Fresh ", "extra": [{"text": "look"}]}],
        }
    }
    pack = write_zip(
        tmp_path / "Fresh.zip",
        {"pack.mcmeta": json.dumps(mcmeta), "pack.png": PNG, "assets/x": "x"},
    )
    meta = read(pack)
    assert (meta.kind, meta.name, meta.description, meta.pack_format) == (
        "resourcepack",
        "Fresh",
        "Fresh look",
        34,
    )
    assert meta.icon == PNG
    assert meta.runs_on(None)


def test_datapack_and_disabled_name(tmp_path):
    pack = write_zip(
        tmp_path / "rules.zip.disabled",
        {
            "pack.mcmeta": '{"pack": {"pack_format": 48, "description": "d"}}',
            "data/x": "x",
        },
    )
    meta = read(pack)
    assert (meta.kind, meta.name) == ("datapack", "rules")


def test_shader_pack_folder(tmp_path):
    folder = tmp_path / "Glow"
    (folder / "shaders").mkdir(parents=True)
    (folder / "shaders" / "final.fsh").write_text("void main() {}")
    assert read(folder) == Metadata(kind="shader", name="Glow")


def test_resource_pack_folder(tmp_path):
    folder = tmp_path / "Loose"
    folder.mkdir()
    (folder / "pack.mcmeta").write_text('{"pack": {"pack_format": 34}}')
    assert read(folder).kind == "resourcepack"


def test_unknown_and_invalid_files(tmp_path):
    assert read(write_zip(tmp_path / "plain.jar", {"a.class": "x"})) is None
    (tmp_path / "broken.jar").write_bytes(b"not a zip")
    assert read(tmp_path / "broken.jar") is None
    with pytest.raises(FileNotFoundError):
        read(tmp_path / "missing.jar")


def test_loader_checks():
    fabric = Metadata(kind="mod", name="F", loaders=("fabric",))
    assert fabric.runs_on("quilt")
    assert not fabric.runs_on("forge")
    assert not fabric.runs_on(None)
    assert Metadata(kind="mod", name="Any").runs_on("forge")


def test_module_is_exported():
    assert ms.metadata.read is read
