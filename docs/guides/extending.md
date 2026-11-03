# Extend Modsmith

Platforms, pack formats and mod loaders each have a base class, so you can add your own without changing Modsmith.

## Add a mod loader

Subclass `Loader`, or `MetaLoader` if the loader publishes a Fabric-style version JSON, and register it. `create` can then find it by name, and packs that use it work like any other. Implement `Loader.available` too, and `versions` and `recommended` will offer its versions. Implement `Loader.from_version`, and `detect` will recognise it in installed versions.

```python
from dataclasses import dataclass
from typing import ClassVar

import modsmith as ms


@ms.loaders.register
@dataclass(frozen=True)
class MyLoader(ms.loaders.MetaLoader):
    kind: ClassVar[str] = "myloader"
    default_maven: ClassVar[str] = "https://maven.example.com/"
    meta_url: str = "https://meta.example.com/v1"

    def profile_url(self) -> str:
        return f"{self.meta_url}/{self.minecraft}/{self.version}/profile.json"


loader = ms.loaders.create("myloader", "1.0.0", "1.21.1")
```

Override `expected_id` if the version id can be worked out without network access, so that `is_installed` works offline.

## Add a modpack format

Subclass `PackFormat`. `index_file` is the file that identifies the format, and `parse` turns it into a `Modpack`.

```python
from pathlib import Path
from typing import Any


class MyFormat(ms.packs.PackFormat):
    name = "myformat"
    index_file = "mypack.json"

    def parse(self, index: dict[str, Any], path: Path) -> ms.packs.Modpack:
        entries = tuple(
            ms.packs.PackEntry(
                path=ms.packs.safe_relative(item["path"]), urls=(item["url"],)
            )
            for item in index["files"]
        )
        return ms.packs.Modpack(
            format=self.name,
            name=index["name"],
            version=index["version"],
            minecraft=index["minecraft"],
            loader_kind=index["loader"],
            loader_version=index["loader_version"],
            entries=entries,
            archive=path,
        )


ms.packs.register(MyFormat())
```

The most recently registered format is tried first. `safe_relative` stops a bad pack from writing outside the instance.

## Add a platform

Subclass `Platform` and implement `search`, `get_project` and `iter_releases`. Implement `get_release` and `identify` too if your platform can look up releases by id or by file contents. `fetch` and `list_releases` then work on their own. Override `resolve` if packs refer to your platform by id.

```python
from collections.abc import Iterator

from modsmith.platforms import Platform, Project, Release, SearchResults


class MyPlatform(Platform):
    name = "myplatform"

    def search(
        self,
        query,
        *,
        project_type="modpack",
        game_version=None,
        loader=None,
        offset=0,
        limit=20,
    ) -> SearchResults:
        return SearchResults((), 0, offset)

    def get_project(self, ref, *, project_type="modpack") -> Project:
        return Project(self.name, str(ref), str(ref), str(ref))

    def iter_releases(
        self, project, *, game_version=None, loader=None, release_only=False
    ) -> Iterator[Release]:
        yield from ()


platform = MyPlatform()
assert list(platform.iter_releases(platform.get_project("example"))) == []
platform.close()
```

Yield the newest release first, so that `next` finds the latest one, and read pages only as they are needed.
