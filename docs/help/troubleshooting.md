# Troubleshooting

Find the message you saw, or the closest match. To see more detail, turn on logging:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

## Launcher

### `No launcher profile in ...; run the launcher once first`

The launcher creates its files the first time it runs. Open it once, close it and try again. If you passed a custom `GameDir`, check that it is the launcher's own folder.

### The new profile does not appear

The launcher may have been open, and it can overwrite its files. Close it, add the profile again, then reopen it.

If that does not help, check that `GameDir.default()` is the folder your launcher uses.

### The game starts without any mods

Check that the profile's version is the loader's version id, such as `fabric-loader-0.16.10-1.21.1`, and not plain `1.21.1`. Use the value that `install` returns.

## Installing a loader

### `Unknown Minecraft version`

Mojang does not publish a version with that name. Check the spelling. `modsmith.minecraft.list_versions` shows what is available.

### `Installers before Minecraft 1.13 are not supported`

Modsmith installs Forge 1.13.2 and later. See [Compatibility](compatibility.md).

### `Hash mismatch for ...`

A processor produced a file that differs from what the installer expected. Modsmith tries other Java runtimes first, so this message means they all failed. If you passed `java=`, try removing it. Otherwise, [report it](https://github.com/PaPa-jun/Modsmith/issues) with the loader and Minecraft versions.

### `Mojang has no ... for ...`

Mojang does not publish that Java runtime for your system. This appears in logs as a warning, and Modsmith moves on to another runtime.

### `No usable Java runtime`

No runtime could be found or downloaded. Check your connection, or pass `java=` with the path of a Java binary.

## Syncing an instance

### `Cannot update ..., so it was left as it was`

A file could not be replaced, and every change was undone. On Windows this usually means the game is running. Close it and run `sync` again.

### `... pack entries have no download`

The pack has files that have to be downloaded by hand. See [Install CurseForge packs](../guides/curseforge.md).

### `Corrupt instance state in ...`

`.modsmith/instance.json` is damaged. Delete the `.modsmith` folder and sync again. Modsmith then treats the folder as new, and replaces files that differ from the pack, so back up anything the player changed first.

### A file I changed was replaced

`sync` keeps a changed file only if it knows what it installed. The first sync into an existing folder has no record, so it replaces files that differ from the pack.

### A change was not detected

`sync` treats a file as unchanged if its size and modification time are the same. See [How sync works](../concepts/sync.md).

## Network

### HTTP 401 or 403 from CurseForge

The API key is missing or invalid. Check `CURSEFORGE_API_KEY`, and create a new key in the [CurseForge console](https://console.curseforge.com/) if needed.

### HTTP 429

You are sending too many requests. Modsmith has already retried. Reuse one platform object, and wait before trying again.

### `Failed to download ...`

Every download location failed. `DownloadError.failures` lists the reason for each file. Run the call again, and it continues where it stopped.

## Still stuck

Open an [issue](https://github.com/PaPa-jun/Modsmith/issues) with your Modsmith version, Python version, system and the full error.
