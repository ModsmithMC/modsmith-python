# Install a mod loader

You usually get a loader from a pack:

```python
import modsmith as ms

game = ms.minecraft.GameDir.default()
pack = ms.packs.load("pack.mrpack")

version_id = pack.install_game(game)
```

`install_game` installs the pack's loader, or plain Minecraft if the pack has none, and returns the version id for a launcher profile. `pack.loader` gives you the loader itself, and is `None` for a vanilla pack.

You can also install one directly. The version comes first, then the Minecraft version:

```python
fabric = ms.loaders.Fabric("0.16.10", "1.21.1")
neoforge = ms.loaders.NeoForge("21.1.233", "1.21.1")
forge = ms.loaders.Forge("47.3.0", "1.20.1")
quilt = ms.loaders.Quilt("0.30.2", "1.21.1")

version_id = fabric.install(game)
```

`install` downloads Minecraft if needed, then the loader. It returns the version id to use in a launcher profile.

## Build a loader from its name

This helps when a name comes from a file or a user:

```python
loader = ms.loaders.create("fabric", "0.16.10", "1.21.1")
loader = ms.loaders.parse("forge-47.3.0", "1.20.1")
```

## Pick a version

When you know only the loader and the Minecraft version, ask for the recommended one:

```python
fabric = ms.loaders.recommended("fabric", "1.21.1")
print(fabric.version)
```

That is the version the loader's project recommends, such as Forge's recommended build, and otherwise its newest stable one. The result is a loader, ready to `install`.

To let a player choose, list the versions, newest first:

```python
for item in ms.loaders.versions("neoforge", "1.21.1")[:5]:
    label = "stable" if item.stable else "pre-release"
    print(item.version, label, "recommended" if item.recommended else "")
```

Each loader publishes its versions differently. NeoForge, for example, keeps one unsorted list for every Minecraft version. `versions` reads each loader's own source and gives the same answer for all of them.

## Check what is installed

```python
if fabric.is_installed(game):
    print(fabric.expected_id())
```

`is_installed` reads local files, so it works offline. Installing a loader that is already there also returns straight away.

## Choose a game directory

`GameDir.default` finds the official launcher's folder. To install somewhere else, give it a path:

```python
game = ms.minecraft.GameDir("my-launcher/minecraft")
```

Vanilla versions work the same way:

```python
for version in ms.minecraft.list_versions()[:5]:
    print(version.id, version.type)

ms.minecraft.install_version(game, "1.21.1")
```

## Forge and NeoForge take longer

Fabric and Quilt only download files. Forge and NeoForge also patch the game, which needs Java and can take a few minutes. Modsmith picks a Java runtime for you, and you can pass your own with `java=`:

```python
from pathlib import Path

forge.install(game, java=Path("/usr/lib/jvm/java-21/bin/java"))
```

[How loaders are installed](../concepts/loaders.md) explains why. Installers are cached, and you can move that cache with `cache_dir=`.

## Supported versions

See [Compatibility](../help/compatibility.md).
