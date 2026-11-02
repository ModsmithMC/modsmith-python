import json
import subprocess
import sys

import pytest

from cursecraft.core.errors import InstanceError, LauncherError
from cursecraft.instances.store import InstanceRecord, InstanceStore
from cursecraft.launcher import detect
from cursecraft.launcher.detect import is_launcher_running
from cursecraft.launcher.profiles import BACKUP_SUFFIX, ProfileStore


def write_profiles(root, name="launcher_profiles.json", **extra):
    path = root / name
    path.write_text(
        json.dumps({"profiles": {"existing": {"name": "Keep"}}, **extra}), encoding="utf-8"
    )
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_requires_launcher_to_have_run(tmp_path):
    with pytest.raises(LauncherError):
        ProfileStore(tmp_path).paths()


def test_upsert_preserves_other_data_and_backs_up(tmp_path):
    path = write_profiles(tmp_path, settings={"crashAssistance": True})
    original = path.read_text(encoding="utf-8")
    ProfileStore(tmp_path).upsert("cursecraft-pack", {"name": "整合包"})
    data = read(path)
    assert data["profiles"]["existing"] == {"name": "Keep"}
    assert data["settings"] == {"crashAssistance": True}
    assert data["profiles"]["cursecraft-pack"]["name"] == "整合包"
    assert "整合包" in path.read_text(encoding="utf-8")
    assert path.with_name(path.name + BACKUP_SUFFIX).read_text(encoding="utf-8") == original
    assert not path.with_name(path.name + ".tmp").exists()


def test_upsert_writes_both_launcher_variants(tmp_path):
    first = write_profiles(tmp_path)
    second = write_profiles(tmp_path, "launcher_profiles_microsoft_store.json")
    ProfileStore(tmp_path).upsert("a", {"name": "A"})
    assert "a" in read(first)["profiles"]
    assert "a" in read(second)["profiles"]


def test_upsert_merges_with_existing_profile(tmp_path):
    write_profiles(tmp_path)
    store = ProfileStore(tmp_path)
    store.upsert("a", {"name": "A", "javaArgs": "-Xmx1G"})
    store.upsert("a", {"name": "B"})
    assert store.get("a") == {"name": "B", "javaArgs": "-Xmx1G"}


def test_remove_profile(tmp_path):
    write_profiles(tmp_path)
    store = ProfileStore(tmp_path)
    store.upsert("a", {"name": "A"})
    store.remove("a")
    store.remove("a")
    assert store.get("a") is None
    assert store.get("existing")


def test_utf8_bom_is_tolerated(tmp_path):
    path = tmp_path / "launcher_profiles.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"profiles": {}}).encode())
    ProfileStore(tmp_path).upsert("a", {"name": "A"})
    assert "a" in read(path)["profiles"]


def test_corrupt_profile_is_left_untouched(tmp_path):
    path = tmp_path / "launcher_profiles.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(LauncherError):
        ProfileStore(tmp_path).upsert("a", {})
    assert path.read_text(encoding="utf-8") == "{oops"


def fake_processes(monkeypatch, platform, stdout):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(
        detect.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout),
    )


def test_detects_windows_launcher(monkeypatch):
    fake_processes(
        monkeypatch,
        "win32",
        '"explorer.exe","1","Console","1","1 K"\n"Minecraft.exe","2","Console","1","1 K"\n',
    )
    assert is_launcher_running()


def test_detects_posix_launcher(monkeypatch):
    fake_processes(monkeypatch, "linux", "/usr/bin/bash\n/opt/minecraft-launcher\n")
    assert is_launcher_running()


def test_no_launcher_running(monkeypatch):
    fake_processes(monkeypatch, "win32", '"explorer.exe","1","Console","1","1 K"\n')
    assert not is_launcher_running()


def test_detection_failure_means_not_running(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError

    monkeypatch.setattr(detect.subprocess, "run", fail)
    assert not is_launcher_running()


def record(slug="pack"):
    return InstanceRecord(
        slug=slug,
        name="Pack",
        source="curseforge",
        project_id=1,
        file_id=2,
        pack_version="1",
        mc_version="1.21.1",
        loader_id="forge-1",
        version_id="1.21.1-forge-1",
        profile_key=f"cursecraft-{slug}",
        files={"mods/a.jar": "abc"},
    )


def test_store_round_trip_and_list(tmp_path):
    store = InstanceStore(tmp_path)
    store.save(record("b"))
    store.save(record("a"))
    (tmp_path / "unrelated").mkdir()
    assert store.load("a") == record("a")
    assert [item.slug for item in store.list()] == ["a", "b"]


def test_store_list_empty_when_missing(tmp_path):
    assert InstanceStore(tmp_path / "none").list() == []


def test_store_delete_only_removes_known_instances(tmp_path):
    store = InstanceStore(tmp_path)
    (tmp_path / "unrelated").mkdir()
    with pytest.raises(InstanceError):
        store.delete("unrelated")
    assert (tmp_path / "unrelated").exists()
    store.save(record())
    store.delete("pack")
    assert not store.exists("pack")


def test_corrupt_record_is_reported(tmp_path):
    store = InstanceStore(tmp_path)
    store.save(record())
    path = tmp_path / "pack" / ".cursecraft" / "instance.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(InstanceError):
        store.load("pack")
