# Search and download

Modrinth and CurseForge share one interface, so the code on this page works with either.

## Connect to a platform

Modrinth needs no key, but asks every client to identify itself:

```python
import modsmith as ms

modrinth = ms.platforms.Modrinth("my-tool/1.0")
```

CurseForge needs an API key from the [CurseForge console](https://console.curseforge.com/):

```python
import os

curseforge = ms.platforms.CurseForge(os.environ["CURSEFORGE_API_KEY"])
```

:::{warning}
Treat the API key as a secret. Read it from the environment rather than writing it in your code.
:::

Both can be used as context managers, which close their connections when you finish.

## Search

```python
results = modrinth.search("sodium", project_type="mod", loader="fabric", limit=5)

print(results.total, "matches")
for project in results.projects:
    print(project.name, project.url, project.downloads)
```

`project_type` is one of `mod`, `modpack`, `resourcepack` or `shader`, and defaults to `modpack`. Use `offset` to read further pages.

Choose the order with `sort`: `relevance`, `downloads`, `popularity`, `newest` or `updated`. Both platforms support all five. CurseForge has no relevance order, so there `relevance` lists the most popular matches first.

```python
popular = modrinth.search("minimap", project_type="mod", sort="downloads", limit=150)
```

`limit` can be larger than a platform serves at once, which is 100 on Modrinth and 50 on CurseForge: Modsmith reads as many pages as it takes. CurseForge stops after 10,000 results.

Each result says who made it, its categories, when it last changed, how many people follow it, and which game releases it supports:

```python
for project in popular.projects[:3]:
    print(project.name, project.author, project.updated[:10], project.game_versions[:3])
```

`author` is `None` for projects looked up with `get_project` on Modrinth, which does not say who made them there. `get_projects` looks up many projects at once, in as few requests as each platform allows.

## Look up a project

`get_project` accepts an id, a slug or a project URL:

```python
project = modrinth.get_project("sodium", project_type="mod")
```

:::{tip}
A slug can change. Store `project.id` if you need to find the project again later.
:::

## Choose a release

`iter_releases` yields releases newest first, and reads pages only as you need them.

```python
latest = next(modrinth.iter_releases(project))
```

That makes one request, however many releases the project has. To show a short list, take only what you need:

```python
from itertools import islice

recent = list(islice(modrinth.iter_releases(project), 20))
```

Filter by what the player is running:

```python
stable = modrinth.iter_releases(
    project, game_version="1.21.1", loader="fabric", release_only=True
)
```

The newest release is not always for the newest game version, so pass `game_version` when it matters. `next` raises `StopIteration` if nothing matches. Give it a default if that can happen:

```python
release = next(modrinth.iter_releases(project, game_version="1.21.1"), None)
```

`latest_release` does the same in one call, and returns `None` when nothing matches. For the Quilt loader it falls back to a Fabric release, because Quilt loads Fabric mods:

```python
release = modrinth.latest_release(project, game_version="1.21.1", loader="quilt")
```

`list_releases` returns every release at once. It has to read every page, which can take many requests on a large CurseForge project.

## Download

`fetch` downloads a release's main file into a folder and returns its path:

```python
if release is not None:
    path = modrinth.fetch(release, "downloads")
    print(path)
```

Each release can have several files. `release.primary_file` is the one `fetch` uses, and `release.files` lists them all.

`release.version` is the version label its author gave, such as `0.6.0`, or `None` on CurseForge, which has none. To show what a release changed, fetch its changelog as plain text:

```python
if release is not None:
    print(modrinth.changelog(release)[:200])
```

Modrinth changelogs are Markdown, which reads well as it is. CurseForge's are HTML, and Modsmith turns them into text, with list items as `-` lines.

```python
modrinth.close()
```

## Respect rate limits

Reuse one platform object rather than creating a new one for each call, and use `iter_releases` to avoid reading pages you do not need. Modsmith waits and retries when a platform asks it to slow down.
