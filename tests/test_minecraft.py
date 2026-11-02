import json
import lzma
import sys
from pathlib import Path

import pytest
import responses

from conftest import fake_java, sha1
from cursecraft.core.errors import JavaNotFoundError, UnsupportedError
from cursecraft.minecraft import java as java_module
from cursecraft.minecraft.java import (
    COMPLETE_MARKER,
    RUNTIME_INDEX_URL,
    JavaResolver,
    find_binary,
    official_runtime_dirs,
    platform_key,
)
from cursecraft.minecraft.versions import VERSION_MANIFEST_URL

META_URL = "https://example.test/1.21.1.json"
JAR_URL = "https://example.test/client.jar"


def stub_version(java=None, jar: bytes = b"client"):
    meta = {
        "id": "1.21.1",
        "downloads": {"client": {"url": JAR_URL, "sha1": sha1(jar), "size": len(jar)}},
    }
    if java:
        meta["javaVersion"] = java
    body = json.dumps(meta).encode()
    responses.get(
        VERSION_MANIFEST_URL,
        json={"versions": [{"id": "1.21.1", "url": META_URL, "sha1": sha1(body)}]},
    )
    responses.get(META_URL, body=body)


@responses.activate
def test_metadata_downloads_and_caches(ctx):
    stub_version()
    ctx.versions.metadata("1.21.1")
    assert ctx.versions.metadata("1.21.1")["id"] == "1.21.1"
    assert ctx.versions.version_file("1.21.1").is_file()
    assert len(responses.calls) == 2


@responses.activate
def test_unknown_version_is_rejected(ctx):
    responses.get(VERSION_MANIFEST_URL, json={"versions": []})
    with pytest.raises(UnsupportedError):
        ctx.versions.metadata("9.9.9")


@responses.activate
def test_ensure_client_replaces_corrupt_jar(ctx):
    stub_version()
    responses.get(JAR_URL, body=b"client")
    jar = ctx.versions.client_jar("1.21.1")
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"broken")
    assert ctx.versions.ensure_client("1.21.1").read_bytes() == b"client"


@responses.activate
def test_java_component_defaults_to_legacy(ctx):
    stub_version()
    assert ctx.versions.java_component("1.21.1") == "jre-legacy"


@responses.activate
def test_java_component_reads_version_json(ctx):
    stub_version({"component": "java-runtime-delta", "majorVersion": 21})
    assert ctx.versions.java_component("1.21.1") == "java-runtime-delta"


def test_store_runtime_dir_is_searched_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    dirs = official_runtime_dirs(tmp_path / "mc")
    assert tmp_path / "mc" / "runtime" in dirs
    assert (
        tmp_path
        / "Packages"
        / java_module.STORE_PACKAGE
        / "LocalCache"
        / "Local"
        / "runtime"
    ) in dirs


def test_find_binary_handles_mac_bundle(tmp_path):
    binary = (
        tmp_path / "c" / "mac-os-arm64" / "c" / "jre.bundle" / "Contents" / "Home" / "bin" / "java"
    )
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    assert find_binary(tmp_path, "c") == binary


def test_candidates_prefer_exact_component(ctx):
    delta = fake_java(ctx.root / "runtime", "java-runtime-delta")
    fake_java(ctx.root / "runtime", "java-runtime-gamma")
    assert ctx.java.candidates("java-runtime-delta") == [delta]


def test_candidates_fall_back_to_other_official_runtimes(ctx):
    delta = fake_java(ctx.root / "runtime", "java-runtime-delta")
    gamma = fake_java(ctx.root / "runtime", "java-runtime-gamma")
    assert ctx.java.candidates("java-runtime-epsilon") == [delta, gamma]


def test_incomplete_cached_runtime_is_ignored(ctx):
    fake_java(ctx.java.cache_runtime_dir, "java-runtime-delta")
    assert ctx.java.find("java-runtime-delta") is None
    (ctx.java.cache_runtime_dir / "java-runtime-delta" / COMPLETE_MARKER).touch()
    assert ctx.java.find("java-runtime-delta") is not None


def runtime_manifest():
    binary = b"java binary"
    packed = lzma.compress(binary)
    text = b"release"
    name = "bin/java.exe" if platform_key().startswith("windows") else "bin/java"
    return {
        "files": {
            "bin": {"type": "directory"},
            name: {
                "type": "file",
                "executable": True,
                "downloads": {
                    "raw": {"sha1": sha1(binary), "url": "https://example.test/raw"},
                    "lzma": {"sha1": sha1(packed), "url": "https://example.test/lzma"},
                },
            },
            "release": {
                "type": "file",
                "executable": False,
                "downloads": {
                    "raw": {"sha1": sha1(text), "url": "https://example.test/release"}
                },
            },
        }
    }, packed, text, name


def stub_runtime():
    manifest, packed, text, name = runtime_manifest()
    responses.get(
        RUNTIME_INDEX_URL,
        json={
            platform_key(): {
                "java-runtime-delta": [{"manifest": {"url": "https://example.test/m"}}]
            }
        },
    )
    responses.get("https://example.test/m", json=manifest)
    responses.get("https://example.test/lzma", body=packed)
    responses.get("https://example.test/release", body=text)
    return name


@responses.activate
def test_download_runtime_into_own_cache(ctx):
    name = stub_runtime()
    binary = ctx.java.download("java-runtime-delta")
    assert binary.read_bytes() == b"java binary"
    assert binary.is_relative_to(ctx.java.cache_runtime_dir)
    assert binary == ctx.java.cache_runtime_dir / "java-runtime-delta" / platform_key() / "java-runtime-delta" / Path(name)
    assert not binary.with_name(binary.name + ".lzma").exists()
    assert ctx.java.find("java-runtime-delta") == binary
    assert not (ctx.root / "runtime").exists()


@responses.activate
def test_download_rejects_platforms_without_runtime(ctx):
    responses.get(RUNTIME_INDEX_URL, json={})
    with pytest.raises(JavaNotFoundError):
        ctx.java.download("java-runtime-delta")


def test_resolver_uses_cache_layout(ctx, tmp_path):
    resolver = JavaResolver(ctx.http, ctx.downloader, ctx.root, tmp_path / "other")
    assert resolver.cache_runtime_dir == tmp_path / "other" / "java"
