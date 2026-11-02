# Platforms and modpack formats

Modsmith gives Modrinth and CurseForge one interface, but the two differ in ways that affect your tool.

| | Modrinth | CurseForge |
| :--- | :--- | :--- |
| API key | Not needed | Required |
| Pack format | `.mrpack` | `.zip` |
| Download links in the pack | Yes | No, they need `resolve` |
| Third-party downloads | Always allowed | The mod author decides |
| Hashes | SHA-1 and SHA-512 | SHA-1 and MD5 |

## Ids and slugs

A slug is the readable name in a project's address, such as `sodium`. An id is a permanent value. Slugs can change, so use `Project.id` for anything you store.

On CurseForge, slugs are only unique within one project type, so pass the right `project_type` when you look one up.

## Identify your tool

Modrinth asks every client to send a user agent that identifies it, so pass your tool's name and version to `Modrinth`. Do not copy the example from these docs.

## Rate limits

Both platforms limit how fast you can send requests. Modsmith retries when it is told to slow down, and waits as long as the server asks, up to one minute.

Reuse one platform object, and prefer `iter_releases` to reading a project's full history.

## How release lists work

`iter_releases` asks for one page at a time, and stops when you stop reading. Filtering with `game_version` or `loader` happens on the server, so it also saves requests. `release_only` is applied by Modsmith, so a project with many beta releases can take more pages.

CurseForge serves at most 10,000 files for one query, so the oldest releases of a very large project may be missing.

## Why some CurseForge files need a manual download

CurseForge lets authors opt out of third-party downloads. The API then gives no download link, and the file has to come from the website. Modsmith keeps these entries in `pack.unresolved` and never tries to guess a link. See [Install CurseForge packs](../guides/curseforge.md).
