# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `Platform.latest_release` returns a project's newest release for a game
  version and loader in one call, falling back from Quilt to Fabric.
- `Platform.search` takes `sort`: `relevance`, `downloads`, `popularity`,
  `newest` or `updated`, the same on both platforms. `limit` may exceed what a
  platform serves at once; the extra pages are read for you.
- `Project` gains `author`, `categories`, `updated`, `follows` and
  `game_versions`, filled the same way on both platforms.
- `Platform.authors` returns the people behind a project, the owner first. It
  fills the gap left by Modrinth project lookups, which name no author.
- `Platform.get_projects` looks up many projects at once. `Instance.plan`,
  `Instance.plan_updates` and `Instance.adopt` use it, so they need far fewer
  requests.
- `Release.version` holds the version label its author gave, and
  `Platform.changelog` returns what a release changed as plain text, converted
  from HTML on CurseForge.
- `modsmith.loaders.versions` lists a loader's versions for a Minecraft version,
  newest first and marked stable or not, the same way for every loader.
  `modsmith.loaders.recommended` returns the one to install by default.
  Loaders that implement `Loader.available` take part.
- `Modpack.install_game` installs what a pack runs on, its mod loader or
  plain Minecraft, and returns the version id for a launcher profile.
- `Instance.remove` takes `dry_run`, to show what a removal would take away,
  dependencies and kept player changes included, before doing it.
- `modsmith.loaders.detect` finds the mod loader an installed version starts,
  from its version JSON alone, so versions the official launcher or a loader's
  installer set up can be recognised. Loaders that implement
  `Loader.from_version` take part.

### Changed

- `Modpack.loader_kind`, `Modpack.loader_version` and `Modpack.loader` are None
  for a pack that needs no mod loader.
- `Modpack.loader_kind` uses the name platforms and instances use, such as
  `fabric` for a pack that says `fabric-loader`.

### Removed

- `Instance.open`. Use `Instance(path)`.
- `modsmith.java.platform_key` and `modsmith.java.official_runtime_dirs`
  are no longer part of the public API.
- `InstallProfile`, `InstallerJar`, `Library` and `Processor` are no longer
  exported from `modsmith.loaders`.
- `Launcher.profile_files`, `Profile.from_dict` and
  `ProcessorLoader.fetch_installer` are now private.

### Fixed

- `loaders.versions("forge", ...)` lists nothing for Minecraft before 1.13,
  since those installers are not supported, instead of versions that then fail
  to install.
- A dependency whose project has only alpha or beta releases, such as a new
  library mod, gets its newest one even with `release_only`, instead of making
  the release that needs it impossible to install. `MissingDependency.project`
  names the project of a dependency that still cannot be met.
- CurseForge searches return the most popular matches first. Before, they came
  back in no useful order, so searching for `jei` did not find JEI.
- CurseForge releases list only game versions in `game_versions`, and their
  loaders in `loaders`, as Modrinth releases do. Before, `game_versions` also
  held labels such as `Client` and `Fabric`, and `loaders` was empty.
- `CurseForge.get_project` finds a slug even when it belongs to another kind of
  project than the one asked for.
- Packs that declare no mod loader can be read and installed. Before, they
  were rejected, although the formats allow them.

## [0.3.0] - 2026-11-03

### Added

- `Instance.plan` and `Instance.add` install single mods, resource packs and
  shader packs, with their dependencies, next to a pack or without one.
  `Instance.plan_updates`, `Instance.remove` and `Instance.pin` update and
  remove them, and `remove` also takes dependencies nothing else needs.
- `Instance.create` starts an instance that does not come from a pack.
- `Instance.disable` and `Instance.enable` switch files off and on with the
  `.disabled` suffix. Syncs and updates keep disabled files disabled.
- `Instance.contents` lists mods, resource packs and shader packs, with where
  each came from, and `Instance.adopt` takes over files the player added.
- `modsmith.metadata` reads what mod jars and packs declare about themselves.
- `Project.folder` names the folder each kind of project goes in.
- `.mrpack` entries hosted on Modrinth carry a `FileRef`, and
  `resolve_dependencies` accepts one as installed.

### Changed

- `modsmith.instances` is now a package, and `InstanceState` has new fields.
  The Minecraft version comes first, `pack_name`, `pack_version`,
  `loader_kind` and `loader_version` can be None, and `loader_kind` uses the
  name platforms use, such as `fabric` rather than `fabric-loader`. State files
  from 0.2 still load.
- CurseForge projects report the type CurseForge gives them, rather than the
  type that was asked for.

## [0.2.0] - 2026-11-03

### Added

- `Release.dependencies`, `Platform.get_release` and
  `modsmith.platforms.resolve_dependencies` for working out which mods a mod
  needs.
- `Platform.identify` finds the releases that files came from, by their
  contents.
- `LockedError`. Installs now use file locks, so several processes can work
  safely: a second sync of one instance fails at once, and installs that share a
  game directory or cache wait for each other.

### Fixed

- Resolving a CurseForge modpack no longer fails when CurseForge knows none of
  its files. They stay unresolved, as unknown files already did.

## [0.1.1] - 2026-11-03

### Fixed

- The Documentation link on PyPI points to the new site,
  <https://modsmith.meneither.site/>.

### Changed

- Project links and the default user agent use the `PaPa-jun/Modsmith`
  repository name.

## [0.1.0] - 2026-11-03

### Added

- `modsmith.platforms`: search and fetch from Modrinth and CurseForge.
- `modsmith.packs`: read mrpack and CurseForge modpacks without network access.
- `modsmith.loaders`: install Forge, NeoForge, Fabric and Quilt.
- `modsmith.instances`: `Instance.diff()` and `Instance.sync()` for installing
  and updating game directories while keeping user changes.
- `modsmith.minecraft`, `modsmith.java`, `modsmith.launcher` and `modsmith.net`.
- `Instance.sync` stages new files and rolls back if it cannot finish, so a
  failed update leaves the instance as it was.
- `Platform.iter_releases` reads releases page by page, so finding the latest
  one takes a single request.
- Modpack overrides are streamed, so large packs no longer load into memory.
- `Instance` remembers file hashes, so a sync with nothing to do is faster.
- `Loader.is_installed` works offline for the built-in loaders.
- Download progress counts skipped and resumed files, and reaches the total.
- Forge and NeoForge installs prefer newer Java runtimes, which fixes old
  versions on Windows and Apple Silicon.
- Requests respect `Retry-After`, and downloads use `If-Range` to resume.

### Changed

- The project was renamed from CurseCraft and rebuilt as a developer toolkit.
