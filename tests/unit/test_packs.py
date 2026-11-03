import json

import pytest

from modsmith.errors import PackError, UnsupportedError
from modsmith.loaders import Fabric, NeoForge
from modsmith.packs import FileRef, PackEntry, load, safe_relative
from tests.lib.builders import (
    mrpack_file,
    write_curseforge_pack,
    write_mrpack,
    write_zip,
)

URL = "https://cdn.invalid/a.jar"


def test_mrpack_is_complete_without_network(tmp_path):
    pack = load(
        write_mrpack(
            tmp_path / "p.mrpack",
            [
                mrpack_file(
                    "a.jar", b"a", URL, {"client": "required", "server": "unsupported"}
                )
            ],
        )
    )
    assert pack.format == "mrpack"
    assert pack.minecraft == "1.21.1"
    assert pack.loader == Fabric("0.16.10", "1.21.1")
    assert pack.unresolved == ()
    entry = pack.entries[0]
    assert entry.path == "mods/a.jar"
    assert entry.urls == (URL,)
    assert entry.server == "unsupported"
    assert not entry.wanted("server")
    assert entry.resource(tmp_path).path == tmp_path / "mods" / "a.jar"


@pytest.mark.parametrize(
    ("key", "expected"),
    [("neoforge", "neoforge"), ("fabric-loader", "fabric"), ("quilt-loader", "quilt")],
)
def test_mrpack_loader_names(tmp_path, key, expected):
    pack = load(write_mrpack(tmp_path / "p.mrpack", loader={key: "1"}))
    assert pack.loader.kind == expected


def test_mrpack_rejects_unsafe_paths(tmp_path):
    file = mrpack_file("a.jar", b"a", URL)
    file["path"] = "../../evil.jar"
    with pytest.raises(PackError, match="Unsafe"):
        load(write_mrpack(tmp_path / "p.mrpack", [file]))


def test_mrpack_rejects_other_games(tmp_path):
    index = {
        "formatVersion": 1,
        "game": "other",
        "name": "x",
        "versionId": "1",
        "files": [],
        "dependencies": {},
    }
    path = write_zip(tmp_path / "p.mrpack", {"modrinth.index.json": json.dumps(index)})
    with pytest.raises(UnsupportedError):
        load(path)


def test_mrpack_with_invalid_index(tmp_path):
    path = write_zip(tmp_path / "p.mrpack", {"modrinth.index.json": "{}"})
    with pytest.raises(PackError):
        load(path)


def test_unknown_loader_only_fails_when_used(tmp_path):
    pack = load(write_mrpack(tmp_path / "p.mrpack", loader={"mystery": "1"}))
    assert pack.loader_kind == "mystery"
    with pytest.raises(UnsupportedError):
        _ = pack.loader


def test_side_overrides_are_applied_last(tmp_path):
    pack = load(
        write_mrpack(
            tmp_path / "p.mrpack",
            overrides={
                "overrides/config/a.txt": "common",
                "overrides/config/b.txt": "common",
                "client-overrides/config/a.txt": "client",
                "server-overrides/config/s.txt": "server",
            },
        )
    )
    written = pack.extract_overrides(tmp_path / "game", "client")
    assert (tmp_path / "game" / "config" / "a.txt").read_text() == "client"
    assert (tmp_path / "game" / "config" / "b.txt").read_text() == "common"
    assert "config/s.txt" not in written


def _manifest(**minecraft):
    return {
        "manifestType": "minecraftModpack",
        "name": "CF Pack",
        "version": "2.0",
        "overrides": "custom",
        "minecraft": {
            "version": "1.21.1",
            "modLoaders": [
                {"id": "fabric-0.1", "primary": False},
                {"id": "neoforge-21.1.233", "primary": True},
            ],
            **minecraft,
        },
        "files": [
            {"projectID": 1, "fileID": 10, "required": True},
            {"projectID": 2, "fileID": 20, "required": False},
        ],
    }


def test_curseforge_pack_needs_resolving(tmp_path):
    pack = load(write_curseforge_pack(tmp_path / "p.zip", _manifest()))
    assert pack.format == "curseforge"
    assert len(pack.unresolved) == 2
    assert pack.entries[0].ref == FileRef("curseforge", "1", "10")


def test_curseforge_honours_primary_loader_required_and_ram(tmp_path):
    path = write_curseforge_pack(tmp_path / "p.zip", _manifest(recommendedRam=6144))
    pack = load(path)
    assert pack.loader == NeoForge("21.1.233", "1.21.1")
    assert pack.memory_mb == 6144
    assert pack.entries[0].wanted("client")
    assert not pack.entries[1].wanted("client")
    assert pack.entries[1].wanted("client", include_optional=True)


def test_curseforge_uses_declared_overrides_dir(tmp_path):
    pack = load(
        write_curseforge_pack(
            tmp_path / "p.zip", _manifest(), {"custom/a.txt": "x", "other/b.txt": "y"}
        )
    )
    assert [path for path, _ in pack.iter_overrides()] == ["a.txt"]


def test_curseforge_requires_loader(tmp_path):
    path = write_curseforge_pack(tmp_path / "p.zip", _manifest(modLoaders=[]))
    with pytest.raises(PackError):
        load(path)


def test_override_path_traversal_is_rejected(tmp_path):
    pack = load(
        write_mrpack(tmp_path / "p.mrpack", overrides={"overrides/../../evil.txt": "x"})
    )
    with pytest.raises(PackError):
        pack.extract_overrides(tmp_path / "game")
    assert not (tmp_path / "evil.txt").exists()


@pytest.mark.parametrize(
    "name", ["../evil", "/etc/passwd", "a/../../b", "C:/x", "a\\b"]
)
def test_safe_relative_rejects(name):
    with pytest.raises(PackError):
        safe_relative(name)


def test_not_a_zip(tmp_path):
    path = tmp_path / "bad.zip"
    path.write_bytes(b"nope")
    with pytest.raises(PackError):
        load(path)


def test_unknown_format(tmp_path):
    with pytest.raises(PackError, match="known"):
        load(write_zip(tmp_path / "x.zip", {"a.txt": "x"}))


def test_entry_is_resolved_only_with_path_and_url():
    assert not PackEntry().is_resolved
    assert not PackEntry(path="a").is_resolved
    assert PackEntry(path="a", urls=("u",)).is_resolved


def test_mrpack_entries_hosted_on_modrinth_name_their_project(tmp_path):
    cdn = "https://cdn.modrinth.com/data/AANobbMI/versions/u1OEbNKx/sodium.jar"
    pack = load(
        write_mrpack(
            tmp_path / "p.mrpack",
            [mrpack_file("sodium.jar", b"s", cdn), mrpack_file("b.jar", b"b", URL)],
        )
    )
    first, second = pack.entries
    assert first.ref == FileRef("modrinth", "AANobbMI", "u1OEbNKx")
    assert second.ref is None
