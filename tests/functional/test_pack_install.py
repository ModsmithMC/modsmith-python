import json
from dataclasses import dataclass
from typing import ClassVar

from modsmith.instances import Instance
from modsmith.loaders import Loader, register
from modsmith.packs import load
from tests.lib.builders import sha1, write_mrpack


def test_vanilla_pack_installs_plain_minecraft(server, session, game, tmp_path):
    jar = b"client"
    game.write_version(
        "1.21.1",
        {
            "id": "1.21.1",
            "downloads": {
                "client": {
                    "url": server.add_body("/client.jar", jar),
                    "sha1": sha1(jar),
                    "size": len(jar),
                }
            },
        },
    )
    pack = load(write_mrpack(tmp_path / "p.mrpack", loader={}))

    assert pack.install_game(game, session=session) == "1.21.1"
    assert game.client_jar("1.21.1").read_bytes() == jar


@register
@dataclass(frozen=True)
class Recorded(Loader):
    """A loader that records the install instead of downloading anything."""

    kind: ClassVar[str] = "recorded-for-tests"
    installed: ClassVar[list[str]] = []

    def version_id(self, *, session=None, cache_dir=None):
        return f"recorded-{self.version}"

    def install(self, game, **options):
        Recorded.installed.append(self.version)
        return self.version_id()


def test_pack_with_a_loader_installs_the_loader(game, tmp_path):
    pack = load(write_mrpack(tmp_path / "p.mrpack", loader={"recorded-for-tests": "7"}))
    assert pack.install_game(game) == "recorded-7"
    assert Recorded.installed == ["7"]


def test_vanilla_pack_syncs_with_no_loader(server, session, tmp_path):
    pack = load(
        write_mrpack(
            tmp_path / "p.mrpack",
            loader={},
            overrides={"overrides/resourcepacks/look.zip": "x"},
        )
    )
    instance = Instance(tmp_path / "game")
    instance.sync(pack, session=session)
    state = instance.state
    assert (state.loader_kind, state.loader_version) == (None, None)
    assert (instance.path / "resourcepacks" / "look.zip").read_text() == "x"
    saved = json.loads((instance.path / ".modsmith" / "instance.json").read_text())
    assert saved["loader_kind"] is None
