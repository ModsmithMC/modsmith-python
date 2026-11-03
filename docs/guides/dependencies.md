# Resolve dependencies

Most mods need other mods. `resolve_dependencies` works out what else to install for a game version and mod loader.

## Find what to install

Choose the releases you want, then resolve them:

```python
import modsmith as ms

with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    iris = modrinth.get_project("iris")
    release = next(
        modrinth.iter_releases(iris, game_version="1.21.1", loader="fabric")
    )

    plan = ms.platforms.resolve_dependencies(
        modrinth,
        [release],
        game_version="1.21.1",
        loader="fabric",
        release_only=False,
    )

    for item in plan.releases:
        print(item.name)
```

`plan.releases` lists each release after the ones it needs. Your own releases are included. Pass `include_optional=True` to add optional dependencies too.

`release_only` is true by default, so a project that only publishes betas counts as missing. Many mods do, so set it to false if you accept pre-releases.

For the Quilt loader, a project with no Quilt release uses its Fabric release, because Quilt can load Fabric mods.

## Check for problems

Problems are returned instead of raised, so you can show them all at once:

```python
for conflict in plan.conflicts:
    print(f"{conflict.release.name} clashes with {conflict.chosen.name}")

for item in plan.missing:
    print(f"{item.release.name} needs something that has no compatible release")
```

A conflict means two releases refuse each other, or two releases need different versions of one project. Each project gets one release and the first choice stands, so Modsmith does not search for another combination of versions. Change the releases you pass in and resolve again.

CurseForge dependencies name a project rather than a version, so Modsmith chooses its newest compatible release.

## Identify files

`identify` finds which releases a set of files came from, using their contents. It works for files a player added by hand, whatever they are called:

```python
from pathlib import Path

with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    jars = list(Path("instances/my-pack/mods").glob("*.jar"))
    known = modrinth.identify(jars)

for path, release in known.items():
    print(path.name, release.project_id, release.name)
```

Files the platform does not know are left out of the result. CurseForge has to read each file slowly to work out its fingerprint, at around 15 MB per second, so pass `progress` to show that work to the player.

## Skip what is already installed

Pass the identified releases as `installed`, so they meet dependencies without being downloaded again:

```python
with ms.platforms.Modrinth("my-tool/1.0") as modrinth:
    plan = ms.platforms.resolve_dependencies(
        modrinth,
        [release],
        game_version="1.21.1",
        loader="fabric",
        release_only=False,
        installed=known.values(),
    )

    for item in plan.releases:
        modrinth.fetch(item, "instances/my-pack/mods")
```

An installed release that a dependency cannot use is reported as a conflict.

Files you add this way are not part of a pack, so `Instance.sync` leaves them alone as the player's own files.
