# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
