# Core concepts

A few Minecraft terms come up throughout these docs. This page explains what each one means and which module handles it.

| Term | What it is | Module |
| :--- | :--- | :--- |
| Launcher | The official app that players use to start the game | `modsmith.launcher` |
| Game directory | The `.minecraft` folder, which holds versions and libraries | `modsmith.minecraft` |
| Version | A playable build of the game, vanilla or with a mod loader | `modsmith.minecraft` |
| Mod loader | Software that lets the game load mods: Forge, NeoForge, Fabric or Quilt | `modsmith.loaders` |
| Modpack | A list of mods and settings that are meant to be played together | `modsmith.packs` |
| Instance | A folder with one modpack's mods, settings and saves | `modsmith.instances` |
| Platform | A site that hosts mods: Modrinth or CurseForge | `modsmith.platforms` |

## How they fit together

A modpack is a recipe. It names a Minecraft version, a mod loader and a list of files.

Installing one touches two separate places:

Game directory
: Shared by every pack. Modsmith installs Minecraft and the mod loader here, so two packs on the same loader share one copy.

Instance
: Belongs to one pack. Modsmith puts its mods and settings here, so packs never affect each other.

A launcher profile ties them together. It says which version to start and which instance to run it in.

:::{warning}
An instance should be its own folder. Do not use the game directory as an instance, because a sync manages the files in that folder.
:::

## Three independent choices

Where a pack came from, what format it is in and which loader it uses are separate. You can read a CurseForge pack that runs on Fabric, or a Modrinth pack that runs on NeoForge, with the same code. That is why these are separate modules, and why you can add to each one on your own. See [Extend Modsmith](../guides/extending.md).

## Common arguments

Long-running calls share the same optional arguments:

`session`
: A `modsmith.net.Session` to reuse. Without one, the call creates its own.

`progress`
: A function that receives updates. See [Show progress and cancel](../guides/progress.md).

`cancel`
: A `modsmith.CancelToken` that stops the call.

Every error Modsmith raises derives from `modsmith.errors.ModsmithError`. See [Handle errors](../guides/errors.md).
