# Add mods and packs

An instance can hold mods, resource packs and shader packs that you add one at a time, next to its pack or without one. Modsmith records each one as an addition, so it can update and remove it later, and a sync of the pack keeps it.

## Start an instance without a pack

```python
import modsmith as ms

instance = ms.instances.Instance.create(
    "instances/my-game", minecraft="1.21.1", loader="fabric"
)
```

`create` only records the versions. Install the game and the loader as [Install a mod loader](loaders.md) shows. An instance made by `sync` already knows its versions, so you can skip this step.

## Plan, then add

```python
with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    plan = instance.plan(modrinth, ["iris"], release_only=False)

    for item in plan.additions:
        print(item.name, "->", item.path)

    instance.add(plan)
```

`plan` changes nothing. For each project it picks the newest release for the instance's game version and loader, then finds what that release needs with `resolve_dependencies`. Anything the pack or an earlier addition already provides counts as installed. `plan.changes` shows which files `add` would write.

To install an exact release, pass the `Release` instead of a project name.

`add` stages and commits files the same way `sync` does, so a failed add leaves the instance as it was.

## Add resource packs and shaders

Pass the kind of project:

```python
with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    plan = instance.plan(
        modrinth, ["complementary-reimagined"], project_type="shader"
    )
    instance.add(plan)
```

Each kind goes in its own folder: `mods`, `resourcepacks` or `shaderpacks`. Datapacks belong to a single world, so they cannot be added to an instance.

## Check the plan

```python
if not plan.ok:
    for conflict in plan.resolution.conflicts:
        print("Conflict:", conflict.release.name, "and", conflict.chosen.name)
    for item in plan.resolution.missing:
        print("Missing:", item.release.name, "needs", item.dependency.project_id)

print("Already in the pack:", [release.name for release in plan.skipped])
print("No release for this version:", plan.unavailable)
```

If `plan.ok` is false, `add` raises `DependencyError` and installs nothing. A missing optional dependency does not stop it.

## Update additions

```python
with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    updates = instance.plan_updates(modrinth, release_only=False)
    instance.add(updates)
```

`plan_updates` looks for newer releases of every addition from that platform. Additions that no longer have a release for the instance's versions are listed in `updates.unavailable`.

Pin an addition to keep it at its release:

```python
instance.pin("iris")
instance.pin("iris", pinned=False)
```

## Remove additions

```python
instance.remove("iris")
```

Dependencies that no other addition needs are removed too. Pass `keep_dependencies=True` to keep them. A file the player changed is kept and listed in `orphaned`.

Only additions can be removed. To stop the game loading a file from the pack, disable it.

## Switch files off

```python
for item in instance.contents():
    print(item.path, item.source, "on" if item.enabled else "off")

shader = instance.contents()[0]
instance.disable(shader.path)
instance.enable(shader.path)
```

Disabling adds a `.disabled` suffix to the file name, which makes the game skip it. This is the same convention other launchers use. Syncs and updates keep disabled files disabled, and update them under their disabled name.

`contents` lists every mod, resource pack and shader pack. `source` says whether the pack installed it, it was added, or the player put it there.

## Read what a file is

```python
for item in instance.contents():
    info = ms.metadata.read(instance.path / item.location)
    if info is not None:
        print(info.kind, info.name, info.version, info.runs_on("fabric"))
```

`modsmith.metadata.read` reads what a jar, zip or folder declares about itself, without network access. `runs_on` checks the loaders a mod declares against the instance's loader.

## Take over files the player added

```python
with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    adopted = instance.adopt(modrinth)
```

`adopt` identifies files the player dropped into the instance by their contents. Those the platform knows become additions, so they can be updated and removed like any other. No file is changed.

## Additions and the pack

`sync` keeps additions in place. If a new version of the pack includes a project you added, the pack takes it over: its file replaces yours, and the addition is listed in `changes.superseded`.
