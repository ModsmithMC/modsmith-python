# Install CurseForge packs

CurseForge packs list project and file ids rather than download links, and some mods can only be downloaded by hand. Your tool has to handle both.

## Look up the files

```python
import os

import modsmith as ms

pack = ms.packs.load("pack.zip")

with ms.platforms.CurseForge(os.environ["CURSEFORGE_API_KEY"]) as curseforge:
    pack = curseforge.resolve(pack)
```

`resolve` returns a new pack with download links filled in. It makes a few batched requests, however many mods the pack has.

## Mods that need a manual download

A mod author can forbid third-party downloads. Those entries stay in `pack.unresolved`, with a page for the player to visit:

```python
for entry in pack.unresolved:
    print(entry.path, entry.manual_url)
```

:::{note}
Do not work around this. It is the mod author's decision, and these files have to come from the player.
:::

A file that CurseForge no longer lists also stays unresolved, but has no `manual_url`.

## Use the downloaded files

Ask the player to download the files, then point `sync` at the folder:

```python
from pathlib import Path

instance = ms.instances.Instance("instances/my-pack")
instance.sync(pack, adopt_from=[Path.home() / "Downloads"])
```

Modsmith finds each file by name and checks its hash, so a wrong file is ignored.

## If files are still missing

If anything is missing, `sync` raises `modsmith.errors.UnresolvedEntriesError` before it changes the instance. The error lists what is needed, so you can show it to the player and try again:

```python
from modsmith.errors import UnresolvedEntriesError

try:
    instance.sync(pack, adopt_from=[Path.home() / "Downloads"])
except UnresolvedEntriesError as error:
    for entry in error.entries:
        print("Please download", entry.manual_url)
```
