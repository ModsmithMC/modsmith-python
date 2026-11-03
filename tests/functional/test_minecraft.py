import json
import threading

import pytest

import modsmith as ms
from modsmith._locks import GAME_LOCK
from modsmith.errors import Cancelled, UnsupportedError
from modsmith.minecraft import install_version, list_versions
from tests.lib.builders import sha1
from tests.lib.locks import held_elsewhere


def publish_version(server, jar=b"client"):
    jar_url = server.add_body("/client.jar", jar)
    meta = {
        "id": "1.21.1",
        "javaVersion": {"component": "java-runtime-delta", "majorVersion": 21},
        "downloads": {"client": {"url": jar_url, "sha1": sha1(jar), "size": len(jar)}},
    }
    body = json.dumps(meta).encode()
    meta_url = server.add_body("/1.21.1.json", body)
    return server.add_json(
        "/manifest.json",
        {
            "versions": [
                {
                    "id": "1.21.1",
                    "type": "release",
                    "url": meta_url,
                    "sha1": sha1(body),
                    "releaseTime": "2024-08-08",
                }
            ]
        },
    )


def test_list_versions(server, session):
    url = publish_version(server)
    versions = list_versions(session, manifest_url=url)
    assert versions[0].id == "1.21.1"
    assert versions[0].type == "release"


def test_install_version_downloads_json_and_client(server, session, game):
    url = publish_version(server)
    version = install_version(game, "1.21.1", session=session, manifest_url=url)
    assert version.java_component == "java-runtime-delta"
    assert game.client_jar("1.21.1").read_bytes() == b"client"


def test_corrupt_jar_is_replaced_without_refetching_metadata(server, session, game):
    jar_url = server.add_body("/client.jar", b"client")
    game.write_version(
        "1.21.1",
        {
            "id": "1.21.1",
            "downloads": {
                "client": {"url": jar_url, "sha1": sha1(b"client"), "size": 6}
            },
        },
    )
    game.client_jar("1.21.1").write_bytes(b"broken")
    install_version(game, "1.21.1", session=session)
    assert game.client_jar("1.21.1").read_bytes() == b"client"
    assert len(server.requests) == 1


def test_unknown_version_is_rejected(server, session, game):
    url = server.add_json("/manifest.json", {"versions": []})
    with pytest.raises(UnsupportedError):
        install_version(game, "9.9", session=session, manifest_url=url)


def test_install_waits_for_the_game_directory(server, session, game):
    manifest = publish_version(server)
    token = ms.CancelToken()
    threading.Timer(0.2, token.cancel).start()
    with held_elsewhere(game.path / GAME_LOCK), pytest.raises(Cancelled):
        install_version(
            game, "1.21.1", session=session, cancel=token, manifest_url=manifest
        )
    assert not game.has_version("1.21.1")

    with held_elsewhere(game.path / GAME_LOCK) as holder:
        holder.release_later(0.2)
        install_version(game, "1.21.1", session=session, manifest_url=manifest)
    assert game.has_version("1.21.1")
