# Read a modpack

`modsmith.packs.load` opens a modpack archive and detects its format. It needs no network and no API key.

```python
import modsmith as ms

pack = ms.packs.load("pack.mrpack")
```

Modsmith reads Modrinth `.mrpack` files and CurseForge `.zip` files. Both give you the same `Modpack` object.

## What a pack contains

```python
print(pack.name, pack.version)
print(pack.minecraft)
print(pack.loader_kind, pack.loader_version)
print(pack.memory_mb)
```

`memory_mb` is the recommended memory, if the pack declares one.

## Files to download

`pack.entries` lists the files the pack needs. Each entry says where the file goes and where to get it:

```python
for entry in pack.entries:
    print(entry.path, entry.size, entry.client)
```

`client` and `server` say how much each side needs the file: `required`, `optional` or `unsupported`. `entry.wanted("client")` applies that for you.

## CurseForge packs need one more step

A Modrinth pack lists its download links, so it is ready to use. A CurseForge pack only lists project and file ids, so you have to look them up:

```python
curseforge_pack = ms.packs.load("pack.zip")
print(len(curseforge_pack.unresolved), "entries need a lookup")
```

See [Install CurseForge packs](curseforge.md).

## Files inside the pack

Packs can also carry files directly, such as configuration. These are called overrides. `override_members` lists them without reading their contents:

```python
for path, info in pack.override_members().items():
    print(path, info.file_size)
```

Read them one at a time, which keeps large packs out of memory:

```python
for path, stream in pack.iter_override_files():
    first_bytes = stream.read(16)
```

To write them all to a folder:

```python
from pathlib import Path

written = pack.extract_overrides(Path("output"))
```

`Instance.sync` handles this for you, so most tools never need these calls.

## Safety

Modsmith rejects packs whose paths could escape the target folder, and raises `modsmith.errors.PackError`. It also raises that error if a file is not a valid modpack.
