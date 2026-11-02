import lzma

import pytest

from modsmith import java
from modsmith.errors import DownloadError, JavaError
from tests.lib.builders import sha1


def place_binary(root, component, relative="bin/java.exe", platform="windows-x64"):
    path = root / component / platform / component / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"java")
    return path


def test_find_prefers_official_runtime(game, tmp_path):
    binary = place_binary(game.path / "runtime", "java-runtime-delta")
    found = java.find("java-runtime-delta", game=game, cache_dir=tmp_path)
    assert found == java.JavaRuntime("java-runtime-delta", binary)


def test_find_handles_macos_bundle(game, tmp_path):
    binary = place_binary(
        game.path / "runtime", "c", "jre.bundle/Contents/Home/bin/java", "mac-os-arm64"
    )
    assert java.find("c", game=game, cache_dir=tmp_path).executable == binary


def test_incomplete_cache_is_ignored(game, tmp_path):
    place_binary(tmp_path / "java", "java-runtime-delta")
    assert java.find("java-runtime-delta", game=game, cache_dir=tmp_path) is None
    (tmp_path / "java" / "java-runtime-delta" / java.COMPLETE_MARKER).touch()
    assert java.find("java-runtime-delta", game=game, cache_dir=tmp_path)


def test_find_all_orders_by_preference(game, tmp_path):
    gamma = place_binary(game.path / "runtime", "java-runtime-gamma")
    delta = place_binary(game.path / "runtime", "java-runtime-delta")
    found = java.find_all(game=game, cache_dir=tmp_path)
    assert [runtime.executable for runtime in found] == [delta, gamma]


def publish_runtime(server):
    binary = b"java binary"
    packed = lzma.compress(binary)
    name = "bin/java.exe" if java.platform_key().startswith("windows") else "bin/java"
    server.add_json(
        "/manifest",
        {
            "files": {
                "bin": {"type": "directory"},
                name: {
                    "type": "file",
                    "executable": True,
                    "downloads": {
                        "raw": {"sha1": sha1(binary), "url": server.url("/raw")},
                        "lzma": {
                            "sha1": sha1(packed),
                            "url": server.add_body("/lzma", packed),
                        },
                    },
                },
                "release": {
                    "type": "file",
                    "executable": False,
                    "downloads": {
                        "raw": {
                            "sha1": sha1(b"r"),
                            "url": server.add_body("/release", b"r"),
                        }
                    },
                },
            }
        },
    )
    return server.add_json(
        "/index",
        {
            java.platform_key(): {
                "java-runtime-delta": [{"manifest": {"url": server.url("/manifest")}}]
            }
        },
    )


def test_download_installs_into_cache_not_launcher(server, session, game, tmp_path):
    index = publish_runtime(server)
    cache = tmp_path / "cache"
    runtime = java.download(
        "java-runtime-delta", cache_dir=cache, session=session, index_url=index
    )
    assert runtime.executable.read_bytes() == b"java binary"
    assert runtime.executable.is_relative_to(cache / "java")
    assert not runtime.executable.with_name(runtime.executable.name + ".lzma").exists()
    assert java.find("java-runtime-delta", game=game, cache_dir=cache) == runtime
    assert not (game.path / "runtime").exists()


def test_download_prefers_compressed_files(server, session, tmp_path):
    index = publish_runtime(server)
    java.download(
        "java-runtime-delta", cache_dir=tmp_path, session=session, index_url=index
    )
    assert server.hits("/raw") == []


def test_corrupt_download_is_rejected(server, session, tmp_path):
    index = publish_runtime(server)
    server.add_body("/lzma", lzma.compress(b"tampered"))
    with pytest.raises(DownloadError):
        java.download(
            "java-runtime-delta", cache_dir=tmp_path, session=session, index_url=index
        )


def test_download_rejects_missing_platform(server, session, tmp_path):
    index = server.add_json("/index", {})
    with pytest.raises(JavaError):
        java.download("x", cache_dir=tmp_path, session=session, index_url=index)
