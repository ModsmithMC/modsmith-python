import json

import pytest

from modsmith.errors import LoaderError, UnsupportedError
from modsmith.loaders import InstallerJar, InstallProfile
from modsmith.loaders._install_profile import Variables, replace_tokens
from modsmith.minecraft import maven_path
from tests.lib.builders import PROFILE_FILES


@pytest.mark.parametrize("path", PROFILE_FILES, ids=lambda p: p.stem)
def test_real_profiles_resolve_every_client_processor(path, tmp_path):
    profile = InstallProfile.parse(json.loads(path.read_text(encoding="utf-8")))
    assert profile.spec in (0, 1)
    tokens = {
        key: value.client[1:-1] if value.client.startswith("'") else "resolved"
        for key, value in profile.data.items()
    }
    tokens.update(
        SIDE="client",
        MINECRAFT_JAR="client.jar",
        MINECRAFT_VERSION=profile.minecraft,
        ROOT="root",
        INSTALLER="installer.jar",
        LIBRARY_DIR="libraries",
    )
    variables = Variables(tmp_path, tokens)
    client = profile.client_processors()
    assert client
    for processor in client:
        maven_path(processor.jar)
        for coord in processor.classpath:
            maven_path(coord)
        for arg in processor.args:
            assert "{" not in variables.resolve(arg)
        for key, value in processor.outputs.items():
            variables.resolve(key)
            resolved = variables.resolve(value)
            assert "'" not in resolved
            assert len(resolved) == 40


def test_real_profiles_hide_server_only_processors():
    path = next(p for p in PROFILE_FILES if p.stem == "forge-1.21.1")
    profile = InstallProfile.parse(json.loads(path.read_text(encoding="utf-8")))
    assert len(profile.client_processors()) < len(profile.processors)


def test_legacy_profile_is_rejected():
    with pytest.raises(UnsupportedError):
        InstallProfile.parse({"install": {}, "versionInfo": {}})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("{A}", "alpha"),
        ("--x={A}/{B}", "--x=alpha/bravo"),
        ("'{A}'", "{A}"),
        (r"\{A\}", "{A}"),
        ("plain", "plain"),
    ],
)
def test_replace_tokens(value, expected):
    assert replace_tokens({"A": "alpha", "B": "bravo"}, value) == expected


@pytest.mark.parametrize("value", ["{MISSING}", "{A", "'a", "a\\"])
def test_replace_tokens_rejects_bad_patterns(value):
    with pytest.raises(LoaderError):
        replace_tokens({"A": "alpha"}, value)


def test_malformed_installer(tmp_path):
    path = tmp_path / "bad.jar"
    path.write_bytes(b"not a zip")
    with pytest.raises(LoaderError):
        InstallerJar(path)
