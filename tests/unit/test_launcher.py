import json

import pytest

from modsmith import launcher
from modsmith.errors import LauncherError
from modsmith.launcher import (
    LAUNCHER_PROCESSES,
    Launcher,
    icon_data_uri,
    is_running,
    parse_ps,
    parse_tasklist,
)
from modsmith.minecraft import GameDir


def write_profiles(root, name="launcher_profiles.json", **extra):
    path = root / name
    path.write_text(
        json.dumps({"profiles": {"existing": {"name": "Keep"}}, **extra}),
        encoding="utf-8",
    )
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    return Launcher(GameDir(tmp_path))


def test_requires_launcher_to_have_run(client):
    with pytest.raises(LauncherError):
        client.profile_files()


def test_add_profile_preserves_other_data_and_backs_up(client, tmp_path):
    path = write_profiles(tmp_path, settings={"crashAssistance": True})
    original = path.read_text(encoding="utf-8")
    key = client.add_profile(
        "整合包 Pack", "1.21-forge", tmp_path / "game", memory_mb=4096
    )
    data = read(path)
    assert key == "modsmith-pack"
    assert data["profiles"]["existing"] == {"name": "Keep"}
    assert data["settings"] == {"crashAssistance": True}
    assert "整合包" in path.read_text(encoding="utf-8")
    profile = client.profiles()[key]
    assert profile.version_id == "1.21-forge"
    assert profile.java_args == "-Xmx4096M"
    assert profile.game_dir == str(tmp_path / "game")
    backup = path.with_name(path.name + launcher.BACKUP_SUFFIX)
    assert backup.read_text(encoding="utf-8") == original


def test_updates_both_launcher_variants(client, tmp_path):
    first = write_profiles(tmp_path)
    second = write_profiles(tmp_path, "launcher_profiles_microsoft_store.json")
    client.add_profile("A", "v", "g", key="a")
    assert "a" in read(first)["profiles"]
    assert "a" in read(second)["profiles"]


def test_update_keeps_created_and_unknown_fields(client, tmp_path):
    path = write_profiles(tmp_path)
    client.add_profile("A", "v1", "g", key="a")
    created = read(path)["profiles"]["a"]["created"]
    client.add_profile("A", "v2", "g", key="a")
    profile = read(path)["profiles"]["a"]
    assert profile["created"] == created
    assert profile["lastVersionId"] == "v2"


def test_remove_profile(client, tmp_path):
    write_profiles(tmp_path)
    client.add_profile("A", "v", "g", key="a")
    client.remove_profile("a")
    client.remove_profile("a")
    assert list(client.profiles()) == ["existing"]


def test_utf8_bom_is_tolerated(client, tmp_path):
    path = tmp_path / "launcher_profiles.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"profiles": {}}).encode())
    client.add_profile("A", "v", "g", key="a")
    assert "a" in read(path)["profiles"]


def test_corrupt_file_is_left_untouched(client, tmp_path):
    path = tmp_path / "launcher_profiles.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(LauncherError):
        client.add_profile("A", "v", "g")
    assert path.read_text(encoding="utf-8") == "{oops"


def test_icon_data_uri():
    assert icon_data_uri(b"x") == "data:image/png;base64,eA=="


def test_parse_tasklist_output():
    output = (
        '"explorer.exe","1","Console","1","1 K"\n'
        '"Minecraft.exe","2","Console","1","1 K"\n'
    )
    assert parse_tasklist(output) & LAUNCHER_PROCESSES == {"minecraft.exe"}


def test_parse_ps_output():
    names = parse_ps("/usr/bin/bash\n/opt/minecraft-launcher\n\n")
    assert names & LAUNCHER_PROCESSES == {"minecraft-launcher"}


def test_is_running_queries_the_real_process_table():
    assert is_running() in (True, False)
    assert launcher._process_names()
