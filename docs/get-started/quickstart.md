# Quickstart

This page installs a real modpack from Modrinth and adds it to the official launcher. It takes a few minutes, because it downloads Minecraft, a mod loader and every mod in the pack.

Before you start, open the official launcher once so that it creates its files, then close it.

## 1. Find a modpack

Every platform identifies your tool with a user agent. Replace `my-tool/1.0` with your own tool's name and version.

```python
import modsmith as ms

with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    project = modrinth.get_project("fabulously-optimized")
    releases = modrinth.iter_releases(project, game_version="1.21.1")
    release = next(releases)
    print(release.name)
    archive = modrinth.fetch(release, ".cache")
```

`iter_releases` yields the newest release first, so `next` gives you the latest one. `fetch` downloads the modpack file and returns its path.

## 2. Read the modpack

```python
pack = ms.packs.load(archive)

print(pack.name, pack.version)
print(pack.minecraft, pack.loader_kind, pack.loader_version)
print(len(pack.entries), "files")
```

Reading a pack needs no network. The `pack` object is the same whichever format or platform it came from.

## 3. Install the mod loader

```python
game = ms.minecraft.GameDir.default()
version_id = pack.loader.install(game)
```

`GameDir.default` is the official launcher's game directory. `install` downloads Minecraft and the mod loader, and returns the id of the new game version. Running it again does nothing.

## 4. Install the files

Each pack gets its own folder, called an instance. Its mods and settings stay separate from your other games.

```python
instance = ms.instances.Instance.open("instances/fabulously-optimized")
changes = instance.sync(pack)

print(len(changes.added), "files added")
```

## 5. Add it to the launcher

```python
launcher = ms.launcher.Launcher(game)
launcher.add_profile(pack.name, version_id, instance.path)
```

Open the official launcher, choose the new installation and press Play.

## Update later

To update, read the newer pack and sync the same instance. Install the new loader version too, in case it changed:

```python
version_id = pack.loader.install(game)
changes = instance.sync(pack)
launcher.add_profile(pack.name, version_id, instance.path)
```

`sync` only downloads what changed, and it keeps any files the player edited. See [Install and update instances](../guides/instances.md).

## Next steps

- [Core concepts](concepts.md) explains how these pieces fit together.
- [Guides](../guides/index.md) cover each task in detail.
