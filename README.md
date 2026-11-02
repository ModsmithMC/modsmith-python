# Modsmith

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Read in Chinese](https://img.shields.io/badge/README-%E4%B8%AD%E6%96%87-red?style=flat-square&logo=github)](README_ZH.md)

A Python toolkit for Minecraft modpacks, mod loaders and game instances.

Modsmith is a library, not a launcher. It gives you composable modules to search Modrinth and CurseForge, read modpacks, install mod loaders, manage game directories and work with the official launcher. It does not sign in to accounts or start the game.

## Example

```python
import modsmith as ms

with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    project = modrinth.get_project("fabulously-optimized")
    release = modrinth.list_releases(project, game_version="1.21.1")[0]
    pack = ms.packs.load(modrinth.fetch(release, ".cache"))

game = ms.minecraft.GameDir.default()
version_id = pack.loader.install(game)

instance = ms.instances.Instance.open("instances/fabulously-optimized")
print(instance.diff(pack))
instance.sync(pack)

ms.launcher.Launcher(game).add_profile(pack.name, version_id, instance.path)
```

Each module also works alone:

```python
pack = ms.packs.load("pack.mrpack")  # no network, no API key
ms.loaders.NeoForge("21.1.233", "1.21.1").install(game)  # only a mod loader
```

## Modules

| Module | Provides |
| :--- | :--- |
| `modsmith.platforms` | `Modrinth`, `CurseForge`, and the `Platform` base class |
| `modsmith.packs` | `load()`, `Modpack`, the mrpack and CurseForge formats |
| `modsmith.loaders` | `Forge`, `NeoForge`, `Fabric`, `Quilt`, and the `Loader` base class |
| `modsmith.instances` | `Instance` with `diff()` and `sync()` |
| `modsmith.minecraft` | `GameDir`, `Version`, vanilla version downloads |
| `modsmith.java` | Find official launcher runtimes or download Mojang's |
| `modsmith.launcher` | Read and change launcher profiles |
| `modsmith.net` | `Resource`, `Session`, verified and resumable `download()` |

Long-running calls accept `progress=` and `cancel=`. Errors derive from `modsmith.errors.ModsmithError`.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks and how the tests are organised.

## License

[MIT](LICENSE)
