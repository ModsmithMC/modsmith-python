# Work with the official launcher

`modsmith.launcher` reads and changes the official launcher's profiles, which are the installations players choose from.

```python
import modsmith as ms

game = ms.minecraft.GameDir.default()
launcher = ms.launcher.Launcher(game)
```

The launcher has to have run once, because that creates its files. Otherwise Modsmith raises `modsmith.errors.LauncherError`.

## Add a profile

```python
key = launcher.add_profile(
    "My Pack",
    "fabric-loader-0.16.10-1.21.1",
    "instances/my-pack",
    memory_mb=6144,
)
```

The arguments are the display name, the version to start and the instance folder. Modsmith stores the folder as an absolute path.

Calling it again with the same name updates the profile, and keeps any fields you did not set. Use the returned `key` to find the profile later.

## Add an icon

```python
from pathlib import Path

if Path("icon.png").is_file():
    icon = ms.launcher.icon_data_uri(Path("icon.png").read_bytes())
    launcher.add_profile("My Pack", "1.21.1", "instances/my-pack", icon=icon)
```

## List and remove profiles

```python
for key, profile in launcher.profiles().items():
    print(key, profile.name, profile.version_id, profile.game_dir)

launcher.remove_profile("modsmith-my-pack")
```

## Keep the launcher closed

The launcher can overwrite its files while it runs, so close it before changing profiles. You can warn the player:

```python
if ms.launcher.is_running():
    print("Please close the Minecraft Launcher first.")
```

:::{note}
`is_running` is a best-effort check. Treat it as a reason to warn the player, not as a guarantee.
:::

Modsmith saves a backup of each file before changing it, next to the original, with the suffix `.modsmith.bak`.
