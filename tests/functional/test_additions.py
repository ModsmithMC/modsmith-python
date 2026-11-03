import dataclasses
import json

import pytest

from modsmith.errors import (
    DependencyError,
    InstanceError,
    LockedError,
    UnsupportedError,
)
from modsmith.instances import Instance
from modsmith.packs import FileRef, load
from modsmith.platforms import ReleaseFile
from tests.lib.builders import mrpack_file, sha1, write_mrpack
from tests.lib.catalog import Catalog, on, release
from tests.lib.locks import held_elsewhere


def published(server, project, version="1", *dependencies, data=None, **options):
    """Build a catalogue release whose file the local server serves."""
    data = data if data is not None else f"{project} {version}".encode()
    name = f"{project}-{version}.jar"
    url = server.add_body(f"/{project}/{version}/{name}", data)
    file = ReleaseFile(name, (url,), {"sha1": sha1(data)}, len(data))
    return release(project, version, *dependencies, files=(file,), **options)


@pytest.fixture
def instance(tmp_path):
    return Instance.create(tmp_path / "game", minecraft="1.21.1", loader="fabric")


def names(instance):
    return sorted(
        path.relative_to(instance.path).as_posix()
        for path in instance.path.rglob("*")
        if path.is_file() and ".modsmith" not in path.parts
    )


def test_create_records_the_versions(tmp_path):
    instance = Instance.create(tmp_path / "game", minecraft="1.21.1")
    state = instance.state
    assert (state.minecraft, state.loader_kind, state.pack_name) == (
        "1.21.1",
        None,
        None,
    )
    with pytest.raises(InstanceError):
        Instance.create(tmp_path / "game", minecraft="1.21.1")


def test_add_installs_a_mod_and_its_dependencies(server, session, instance):
    catalog = Catalog(published(server, "a", "1", on("b")), published(server, "b"))

    plan = instance.plan(catalog, ["a"])
    assert plan.ok
    assert sorted(plan.changes.added) == ["mods/a-1.jar", "mods/b-1.jar"]
    assert names(instance) == []

    changes = instance.add(plan, session=session)

    assert sorted(changes.added) == ["mods/a-1.jar", "mods/b-1.jar"]
    assert names(instance) == ["mods/a-1.jar", "mods/b-1.jar"]
    additions = {item.project_id: item for item in instance.additions}
    assert additions["a"].requested
    assert additions["a"].requires == ("b",)
    assert not additions["b"].requested
    assert additions["a"].sha1 == sha1(b"a 1")
    assert additions["a"].release_id == "a-1"


def test_resource_packs_and_shaders_go_in_their_folders(server, session, instance):
    catalog = Catalog(
        published(server, "look", loader="minecraft"),
        published(server, "glow", loader="iris"),
        types={"look": "resourcepack", "glow": "shader"},
    )
    instance.add(
        instance.plan(catalog, ["look"], project_type="resourcepack"), session=session
    )
    instance.add(
        instance.plan(catalog, ["glow"], project_type="shader"), session=session
    )
    assert names(instance) == ["resourcepacks/look-1.jar", "shaderpacks/glow-1.jar"]


def test_mods_need_a_loader(tmp_path):
    instance = Instance.create(tmp_path / "game", minecraft="1.21.1")
    with pytest.raises(UnsupportedError):
        instance.plan(Catalog(release("a")), ["a"])
    with pytest.raises(UnsupportedError):
        instance.plan(Catalog(release("a")), ["a"], project_type="modpack")


def test_plan_needs_an_instance(tmp_path):
    with pytest.raises(InstanceError):
        Instance.open(tmp_path / "nothing").plan(Catalog(release("a")), ["a"])


def test_projects_without_a_compatible_release_are_unavailable(server, instance):
    catalog = Catalog(published(server, "old", game="1.20.1"), published(server, "a"))
    plan = instance.plan(catalog, ["old", "a"])
    assert plan.unavailable == ("old",)
    assert [item.project_id for item in plan.additions] == ["a"]


def test_conflicts_stop_the_add(server, session, instance):
    catalog = Catalog(
        published(server, "a", "1", on("c", exact="c-1")),
        published(server, "b", "1", on("c", exact="c-2")),
        published(server, "c", "2"),
        published(server, "c", "1"),
    )
    plan = instance.plan(catalog, ["a", "b"])
    assert not plan.ok
    with pytest.raises(DependencyError) as caught:
        instance.add(plan, session=session)
    assert caught.value.plan is plan
    assert names(instance) == []


def test_missing_optional_dependency_does_not_stop_the_add(server, session, instance):
    catalog = Catalog(published(server, "a", "1", on("gone", kind="optional")))
    plan = instance.plan(catalog, ["a"], include_optional=True)
    assert plan.resolution.missing
    assert plan.ok
    instance.add(plan, session=session)
    assert names(instance) == ["mods/a-1.jar"]


def test_updates_replace_old_releases(server, session, instance):
    catalog = Catalog(published(server, "a", "1", on("b")), published(server, "b"))
    instance.add(instance.plan(catalog, ["a"]), session=session)
    assert not instance.plan_updates(catalog).additions

    catalog.publish(published(server, "b", "2"))
    plan = instance.plan_updates(catalog)
    assert [item.release_id for item in plan.additions] == ["b-2"]
    changes = instance.add(plan, session=session)

    assert changes.added == ("mods/b-2.jar",)
    assert changes.removed == ("mods/b-1.jar",)
    assert names(instance) == ["mods/a-1.jar", "mods/b-2.jar"]
    additions = {item.project_id: item for item in instance.additions}
    assert not additions["b"].requested


def test_pinned_additions_are_not_updated(server, session, instance):
    catalog = Catalog(published(server, "a"))
    instance.add(instance.plan(catalog, ["a"]), session=session)
    assert instance.pin("a").pinned
    catalog.publish(published(server, "a", "2"))
    assert not instance.plan_updates(catalog).additions
    instance.pin("a", pinned=False)
    assert [item.release_id for item in instance.plan_updates(catalog).additions] == [
        "a-2"
    ]
    with pytest.raises(InstanceError):
        instance.pin("nothing")


def test_additions_with_no_release_left_are_unavailable(server, session, instance):
    catalog = Catalog(published(server, "a"))
    instance.add(instance.plan(catalog, ["a"]), session=session)
    catalog.releases.clear()
    catalog.publish(published(server, "a", "2", game="1.20.1"))
    assert instance.plan_updates(catalog).unavailable == ("a",)


def test_remove_takes_unneeded_dependencies_with_it(server, session, instance):
    catalog = Catalog(
        published(server, "a", "1", on("lib")),
        published(server, "b", "1", on("lib")),
        published(server, "lib"),
    )
    instance.add(instance.plan(catalog, ["a", "b"]), session=session)

    changes = instance.remove("a")
    assert changes.removed == ("mods/a-1.jar",)
    assert names(instance) == ["mods/b-1.jar", "mods/lib-1.jar"]

    changes = instance.remove("b")
    assert sorted(changes.removed) == ["mods/b-1.jar", "mods/lib-1.jar"]
    assert instance.additions == ()


def test_remove_can_keep_dependencies(server, session, instance):
    catalog = Catalog(published(server, "a", "1", on("lib")), published(server, "lib"))
    instance.add(instance.plan(catalog, ["a"]), session=session)
    instance.remove("mods/a-1.jar", keep_dependencies=True)
    assert names(instance) == ["mods/lib-1.jar"]


def test_remove_keeps_files_the_player_changed(server, session, instance):
    catalog = Catalog(published(server, "a"))
    instance.add(instance.plan(catalog, ["a"]), session=session)
    (instance.path / "mods" / "a-1.jar").write_bytes(b"patched")
    changes = instance.remove("a")
    assert changes.orphaned == ("mods/a-1.jar",)
    assert (instance.path / "mods" / "a-1.jar").read_bytes() == b"patched"


def test_remove_refuses_files_it_did_not_add(server, session, instance):
    with pytest.raises(InstanceError):
        instance.remove("mods/user.jar")


def test_add_keeps_a_player_file_with_the_same_name(server, session, instance):
    catalog = Catalog(published(server, "a"))
    (instance.path / "mods").mkdir()
    (instance.path / "mods" / "a-1.jar").write_bytes(b"mine")
    changes = instance.add(instance.plan(catalog, ["a"]), session=session)
    assert changes.conflicts == ("mods/a-1.jar",)
    assert (instance.path / "mods" / "a-1.jar").read_bytes() == b"mine"
    assert instance.state.kept == ("mods/a-1.jar",)

    instance.add(instance.plan(catalog, ["a"]), overwrite=True, session=session)
    assert (instance.path / "mods" / "a-1.jar").read_bytes() == b"a 1"
    assert instance.state.kept == ()


def test_disabled_files_stay_disabled_through_updates(server, session, instance):
    catalog = Catalog(published(server, "a"))
    instance.add(instance.plan(catalog, ["a"]), session=session)
    instance.disable("mods/a-1.jar")
    instance.disable("mods/a-1.jar")
    assert names(instance) == ["mods/a-1.jar.disabled"]

    # A pinned release is the same file, so nothing is downloaded again.
    calls = len(server.requests)
    assert instance.add(instance.plan(catalog, ["a"]), session=session).unchanged == (
        "mods/a-1.jar",
    )
    assert len(server.requests) == calls

    instance.enable("mods/a-1.jar.disabled")
    assert names(instance) == ["mods/a-1.jar"]
    with pytest.raises(InstanceError):
        instance.enable("mods/missing.jar")


def test_disabling_refuses_when_both_names_exist(instance):
    (instance.path / "mods").mkdir()
    (instance.path / "mods" / "a.jar").write_bytes(b"a")
    (instance.path / "mods" / "a.jar.disabled").write_bytes(b"a")
    with pytest.raises(InstanceError):
        instance.disable("mods/a.jar")


def test_sync_keeps_additions_and_disabled_pack_files(server, session, tmp_path):
    data = b"pack mod"
    url = server.add_body("/pack.jar", data)
    pack = load(
        write_mrpack(tmp_path / "p.mrpack", [mrpack_file("pack.jar", data, url)])
    )
    instance = Instance.open(tmp_path / "game")
    instance.sync(pack, session=session)
    catalog = Catalog(published(server, "a"))
    instance.add(instance.plan(catalog, ["a"]), session=session)
    instance.disable("mods/pack.jar")

    calls = len(server.requests)
    changes = instance.sync(pack, session=session)

    assert sorted(changes.unchanged) == ["mods/a-1.jar", "mods/pack.jar"]
    assert len(server.requests) == calls
    assert names(instance) == ["mods/a-1.jar", "mods/pack.jar.disabled"]
    assert [item.project_id for item in instance.additions] == ["a"]


def test_pack_takes_over_an_addition_it_now_provides(server, session, tmp_path):
    instance = Instance.open(tmp_path / "game")
    empty = load(write_mrpack(tmp_path / "v1.mrpack"))
    instance.sync(empty, session=session)
    catalog = Catalog(published(server, "a"))
    instance.add(instance.plan(catalog, ["a"]), session=session)

    data = b"a from the pack"
    url = server.add_body("/a-pack.jar", data)
    built = load(
        write_mrpack(tmp_path / "v2.mrpack", [mrpack_file("a-pack.jar", data, url)])
    )
    ref = FileRef("catalog", "a", "a-9")
    pack = built.with_entries(
        tuple(dataclasses.replace(entry, ref=ref) for entry in built.entries)
    )

    assert instance.diff(pack).superseded == ("mods/a-1.jar",)
    changes = instance.sync(pack, session=session)

    assert changes.superseded == ("mods/a-1.jar",)
    assert changes.removed == ("mods/a-1.jar",)
    assert names(instance) == ["mods/a-pack.jar"]
    assert instance.additions == ()
    assert instance.state.pack_refs == (ref,)

    plan = instance.plan(catalog, ["a"])
    assert [item.id for item in plan.skipped] == ["a-1"]
    assert plan.additions == ()


def test_contents_shows_where_files_came_from(server, session, tmp_path):
    data = b"pack mod"
    url = server.add_body("/pack.jar", data)
    pack = load(
        write_mrpack(tmp_path / "p.mrpack", [mrpack_file("pack.jar", data, url)])
    )
    instance = Instance.open(tmp_path / "game")
    instance.sync(pack, session=session)
    instance.add(instance.plan(Catalog(published(server, "a")), ["a"]), session=session)
    (instance.path / "mods" / "mine.jar.disabled").write_bytes(b"mine")
    (instance.path / "mods" / "folder").mkdir()
    (instance.path / "resourcepacks" / "unzipped").mkdir(parents=True)

    found = {item.path: item for item in instance.contents()}

    assert sorted(found) == [
        "mods/a-1.jar",
        "mods/mine.jar",
        "mods/pack.jar",
        "resourcepacks/unzipped",
    ]
    assert found["mods/a-1.jar"].source == "addition"
    assert found["mods/a-1.jar"].addition.project_id == "a"
    assert found["mods/pack.jar"].source == "pack"
    assert found["mods/mine.jar"].source == "user"
    assert not found["mods/mine.jar"].enabled
    assert found["mods/mine.jar"].location == "mods/mine.jar.disabled"


def test_adopt_takes_over_files_the_platform_knows(server, session, instance):
    catalog = Catalog(published(server, "a", "1", on("b")), published(server, "b"))
    (instance.path / "mods").mkdir()
    (instance.path / "mods" / "renamed.jar").write_bytes(b"a 1")
    (instance.path / "mods" / "b.jar.disabled").write_bytes(b"b 1")
    (instance.path / "mods" / "unknown.jar").write_bytes(b"?")

    adopted = instance.adopt(catalog)

    assert sorted(item.path for item in adopted) == ["mods/b.jar", "mods/renamed.jar"]
    found = {item.project_id: item for item in instance.additions}
    assert found["a"].path == "mods/renamed.jar"
    assert found["a"].requires == ("b",)
    assert found["a"].sha1 == sha1(b"a 1")
    assert instance.adopt(catalog) == ()

    calls = len(server.requests)
    assert instance.plan_updates(catalog).additions == ()
    # Adopted files count as requested, because nothing says otherwise.
    instance.remove("a")
    assert names(instance) == ["mods/b.jar.disabled", "mods/unknown.jar"]
    instance.remove("b")
    assert names(instance) == ["mods/unknown.jar"]
    assert len(server.requests) == calls


def test_changes_wait_for_no_one(server, session, instance):
    with (
        held_elsewhere(instance.path / ".modsmith" / "lock"),
        pytest.raises(LockedError),
    ):
        instance.add(
            instance.plan(Catalog(published(server, "a")), ["a"]), session=session
        )


def test_state_from_older_versions_still_reads(tmp_path):
    path = tmp_path / "game" / ".modsmith" / "instance.json"
    path.parent.mkdir(parents=True)
    old = {
        "pack_name": "P",
        "pack_version": "1.0",
        "minecraft": "1.21.1",
        "loader_kind": "fabric-loader",
        "loader_version": "0.16.10",
        "files": {"mods/a.jar": "x"},
        "kept": [],
        "synced_at": "2026-11-01T00:00:00+00:00",
    }
    path.write_text(json.dumps(old))
    state = Instance.open(tmp_path / "game").state
    assert state.pack_name == "P"
    assert state.loader_kind == "fabric"
    assert state.additions == ()
    assert state.pack_refs == ()
