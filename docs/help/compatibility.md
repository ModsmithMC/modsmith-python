# Compatibility

Last verified against Minecraft 26.3, in November 2026.

| | Supported |
| :--- | :--- |
| Python | 3.12 and later |
| Operating systems | Windows, macOS and Linux |
| Platforms | Modrinth and CurseForge |
| Modpack formats | `.mrpack` and CurseForge `.zip` |
| Launcher | Official Minecraft Launcher, including the Microsoft Store version |
| Edition | Java Edition |

## Mod loaders

| Loader | Minecraft versions |
| :--- | :--- |
| Forge | 1.12.2 (from 14.23.5.2851) and later |
| NeoForge | 1.20.1 and later |
| Fabric | 1.14 and later |
| Quilt | 1.14.4 and later |

The oldest and newest versions of each loader are installed by automated tests against the real services. Those tests check that the game files are complete, but they do not start the game.

## Apple Silicon

Mojang publishes no `jre-legacy` for Apple Silicon, so Modsmith installs older Forge versions with a newer Java. Whether those old versions then run is decided by the official launcher.
