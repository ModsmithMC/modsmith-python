import json

import pytest
import responses

import modsmith as ms
from helpers import mrpack, mrpack_file, sha1
from modsmith.errors import Cancelled, InstanceError, UnresolvedEntriesError
from modsmith.instances import Instance
from modsmith.packs import PackEntry, load

CDN = "https://cdn.test"


def mod(name, data, **kwargs):
    url = f"{CDN}/{name}"
    responses.get(url, body=data)
    return mrpack_file(name, data, url, **kwargs)


def pack_of(tmp_path, files=(), overrides=None, version="1.0", name="p.mrpack"):
    return load(mrpack(tmp_path / "built" / name, files, overrides, version=version))


@pytest.fixture
def instance(tmp_path):
    return Instance.open(tmp_path / "game")


@responses.activate
def test_first_sync_installs_everything(instance, tmp_path, session):
    pack = pack_of(tmp_path, [mod("a.jar", b"a")], {"overrides/config/x.toml": "x=1"})

    changes = instance.diff(pack)
    assert sorted(changes.added) == ["config/x.toml", "mods/a.jar"]
    assert not instance.path.exists()

    result = instance.sync(pack, session=session)

    assert sorted(result.added) == ["config/x.toml", "mods/a.jar"]
    assert (instance.path / "mods" / "a.jar").read_bytes() == b"a"
    assert (instance.path / "config" / "x.toml").read_text() == "x=1"
    state = instance.state
    assert state.pack_version == "1.0"
    assert state.files == {"mods/a.jar": sha1(b"a"), "config/x.toml": sha1(b"x=1")}


@responses.activate
def test_sync_is_idempotent(instance, tmp_path, session):
    pack = pack_of(tmp_path, [mod("a.jar", b"a")], {"overrides/x": "x"})
    instance.sync(pack, session=session)
    calls = len(responses.calls)
    changes = instance.sync(pack, session=session)
    assert changes.added == changes.updated == changes.removed == ()
    assert sorted(changes.unchanged) == ["mods/a.jar", "x"]
    assert len(responses.calls) == calls


@responses.activate
def test_update_replaces_managed_files_and_keeps_user_changes(instance, tmp_path, session):
    old = pack_of(
        tmp_path,
        [mod("old.jar", b"old")],
        {"overrides/keep": "v1", "overrides/take": "v1", "overrides/gone": "v1"},
    )
    instance.sync(old, session=session)
    (instance.path / "keep").write_text("mine")
    (instance.path / "mods" / "user-added.jar").write_bytes(b"mine")

    new = pack_of(
        tmp_path,
        [mod("new.jar", b"new")],
        {"overrides/keep": "v2", "overrides/take": "v2"},
        "2.0",
        "new.mrpack",
    )
    preview = instance.diff(new)
    assert preview.conflicts == ("keep",)
    assert sorted(preview.removed) == ["gone", "mods/old.jar"]

    changes = instance.sync(new, session=session)

    assert not (instance.path / "mods" / "old.jar").exists()
    assert (instance.path / "mods" / "new.jar").read_bytes() == b"new"
    assert (instance.path / "mods" / "user-added.jar").exists()
    assert (instance.path / "keep").read_text() == "mine"
    assert (instance.path / "take").read_text() == "v2"
    assert not (instance.path / "gone").exists()
    assert changes.conflicts == ("keep",)
    assert instance.state.kept == ("keep",)
    assert instance.state.pack_version == "2.0"


@responses.activate
def test_kept_file_stays_a_conflict_on_later_updates(instance, tmp_path, session):
    instance.sync(pack_of(tmp_path, overrides={"overrides/a": "v1"}), session=session)
    (instance.path / "a").write_text("mine")
    second = pack_of(tmp_path, overrides={"overrides/a": "v2"}, name="2.mrpack")
    instance.sync(second, session=session)
    third = pack_of(tmp_path, overrides={"overrides/a": "v3"}, name="3.mrpack")
    assert instance.diff(third).conflicts == ("a",)


@responses.activate
def test_overwrite_replaces_user_changes(instance, tmp_path, session):
    instance.sync(pack_of(tmp_path, overrides={"overrides/a": "v1"}), session=session)
    (instance.path / "a").write_text("mine")
    new = pack_of(tmp_path, overrides={"overrides/a": "v2"}, name="2.mrpack")
    instance.sync(new, overwrite=True, session=session)
    assert (instance.path / "a").read_text() == "v2"
    assert instance.state.kept == ()


@responses.activate
def test_removed_file_edited_by_user_is_orphaned_not_deleted(instance, tmp_path, session):
    instance.sync(pack_of(tmp_path, overrides={"overrides/a": "v1"}), session=session)
    (instance.path / "a").write_text("mine")
    changes = instance.sync(pack_of(tmp_path, name="2.mrpack"), session=session)
    assert changes.orphaned == ("a",)
    assert (instance.path / "a").exists()


@responses.activate
def test_first_sync_replaces_leftovers(instance, tmp_path, session):
    pack = pack_of(tmp_path, overrides={"overrides/a": "new"})
    (instance.path).mkdir()
    (instance.path / "a").write_text("partial")
    assert instance.sync(pack, session=session).updated == ("a",)
    assert (instance.path / "a").read_text() == "new"


@responses.activate
def test_side_and_optional_filtering(instance, tmp_path, session):
    pack = pack_of(
        tmp_path,
        [
            mod("client.jar", b"c", env={"client": "required", "server": "unsupported"}),
            mod("server.jar", b"s", env={"client": "unsupported", "server": "required"}),
            mod("extra.jar", b"e", env={"client": "optional", "server": "optional"}),
        ],
    )
    assert instance.diff(pack).added == ("mods/client.jar",)
    assert instance.diff(pack, side="server").added == ("mods/server.jar",)
    assert sorted(instance.diff(pack, include_optional=True).added) == [
        "mods/client.jar",
        "mods/extra.jar",
    ]


def unresolved_pack(tmp_path, data=b"blocked"):
    pack = pack_of(tmp_path)
    entry = PackEntry(
        path="mods/blocked.jar",
        hashes={"sha1": sha1(data)},
        manual_url="https://example.test/blocked",
    )
    return pack.with_entries((entry,))


def test_unresolved_entries_stop_sync_before_writing(instance, tmp_path, session):
    with pytest.raises(UnresolvedEntriesError) as error:
        instance.sync(unresolved_pack(tmp_path), session=session)
    assert error.value.entries[0].manual_url == "https://example.test/blocked"
    assert not instance.path.exists()


def test_unidentified_entries_stop_sync(instance, tmp_path, session):
    pack = pack_of(tmp_path).with_entries((PackEntry(),))
    with pytest.raises(UnresolvedEntriesError):
        instance.sync(pack, session=session)


def test_adopt_verifies_files(instance, tmp_path, session):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "blocked.jar").write_bytes(b"tampered")
    pack = unresolved_pack(tmp_path)
    with pytest.raises(UnresolvedEntriesError):
        instance.sync(pack, adopt_from=[downloads], session=session)

    (downloads / "blocked.jar").write_bytes(b"blocked")
    instance.sync(pack, adopt_from=[downloads], session=session)
    assert (instance.path / "mods" / "blocked.jar").read_bytes() == b"blocked"
    assert instance.state.files == {"mods/blocked.jar": sha1(b"blocked")}


@responses.activate
def test_interrupted_sync_resumes(instance, tmp_path, session):
    url = f"{CDN}/b.jar"
    good = mod("a.jar", b"a")
    pack = pack_of(tmp_path, [good, mrpack_file("b.jar", b"b", url)])
    responses.get(url, status=404)
    with pytest.raises(ms.errors.DownloadError):
        instance.sync(pack, session=session)
    assert instance.state is None

    responses.replace(responses.GET, url, body=b"b")
    instance.sync(pack, session=session)
    assert (instance.path / "mods" / "b.jar").read_bytes() == b"b"
    calls = [c for c in responses.calls if c.request.url.endswith("a.jar")]
    assert len(calls) == 1


@responses.activate
def test_cancel_leaves_no_state(instance, tmp_path, session):
    pack = pack_of(tmp_path, overrides={"overrides/a": "x"})
    token = ms.CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        instance.sync(pack, session=session, cancel=token)
    assert instance.state is None


@responses.activate
def test_delete(instance, tmp_path, session):
    instance.sync(pack_of(tmp_path), session=session)
    instance.delete()
    assert not instance.path.exists()


def test_delete_refuses_unmanaged_directory(instance):
    instance.path.mkdir()
    (instance.path / "precious").write_text("x")
    with pytest.raises(InstanceError):
        instance.delete()
    assert (instance.path / "precious").exists()


def test_corrupt_state_is_reported(instance):
    path = instance.path / ".modsmith" / "instance.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(InstanceError):
        _ = instance.state
