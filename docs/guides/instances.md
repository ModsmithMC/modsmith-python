# Install and update instances

An instance is a folder with one modpack's files. Install and update are the same call, `sync`.

```python
import modsmith as ms

pack = ms.packs.load("pack.mrpack")
instance = ms.instances.Instance("instances/my-pack")

changes = instance.sync(pack)
```

The folder is created by the first sync. Modsmith records what it installed in a `.modsmith` folder inside it.

To add single mods, resource packs or shaders next to the pack, or to start an instance without one, see [Add mods and packs](additions.md). A sync keeps those additions.

## Preview changes

`diff` shows what a sync would do, and changes nothing:

```python
changes = instance.diff(pack)

print("New:", changes.added)
print("Updated:", changes.updated)
print("Removed:", changes.removed)
print("Changed by the player:", changes.conflicts)
print("No longer in the pack:", changes.orphaned)
```

## Player changes are kept

If a player edits a file and the pack also changes it, `sync` keeps the player's version and lists the file in `changes.conflicts`. New files they added are never touched.

To replace their changes instead, ask for it:

```python
instance.sync(pack, overwrite=True)
```

:::{tip}
Show `changes.conflicts` to the player and let them choose, rather than passing `overwrite=True` by default.
:::

## What was installed

```python
state = instance.state
if state is not None:
    print(state.pack_name, state.pack_version, state.synced_at)
    print(state.minecraft, state.loader_kind)
```

`state` is `None` if the folder is not an instance yet. `pack_name` and `pack_version` are `None` for an instance made with `Instance.create`.

## Choose what to install

```python
instance.sync(pack, include_optional=True)
```

Use `side="server"` to install a server's files instead of a client's.

## If a sync fails

A failed sync leaves the instance as it was. Run it again, and it continues with the files it already downloaded.

Close the game before you sync. On Windows, a running game locks its mods, so the sync stops and raises `modsmith.errors.InstanceError`. [How sync works](../concepts/sync.md) has the details.

## Delete an instance

```python
instance.delete()
```

`delete` removes the whole folder, including the player's saves. It refuses to delete a folder that Modsmith did not install.
