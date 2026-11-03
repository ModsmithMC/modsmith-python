"""Read what mods and packs say about themselves, without network access.

Mod jars declare their name, version and loader in ``fabric.mod.json``,
``quilt.mod.json``, ``META-INF/neoforge.mods.toml``, ``META-INF/mods.toml`` or
``mcmod.info``. Resource packs and datapacks have ``pack.mcmeta``, and shader
packs have a ``shaders`` folder.
"""

import json
import tomllib
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from .loaders._base import LOADER_FALLBACKS

__all__ = ["Metadata", "read"]

Kind = Literal["mod", "resourcepack", "datapack", "shader"]
# Forge fills these in from the jar's manifest when it loads the mod.
JAR_VERSION = "${file.jarVersion}"


@dataclass(frozen=True)
class Metadata:
    """What a mod or pack declares about itself.

    Attributes:
        kind: ``mod``, ``resourcepack``, ``datapack`` or ``shader``.
        name: The display name. Shader packs have none, so their file name is used.
        id: The mod's id, or None for packs.
        version: The version, or None if not declared.
        description: The description.
        authors: The authors' names.
        loaders: The mod loaders it declares support for. Empty for packs.
        pack_format: The resource or data pack format, or None.
        icon: The icon's PNG data, or None.
    """

    kind: Kind
    name: str
    id: str | None = None
    version: str | None = None
    description: str = ""
    authors: tuple[str, ...] = ()
    loaders: tuple[str, ...] = ()
    pack_format: int | None = None
    icon: bytes | None = field(default=None, repr=False, compare=False)

    def runs_on(self, loader: str | None) -> bool:
        """Return whether a game with this mod loader can load it.

        Packs work with any loader. A mod that declares no loader is assumed to
        work, and Quilt also loads Fabric mods.

        Args:
            loader: The loader's name, or None for vanilla.

        Returns:
            True if it is expected to load.
        """
        if self.kind != "mod" or not self.loaders:
            return True
        if loader is None:
            return False
        accepted = LOADER_FALLBACKS.get(loader, (loader,))
        return any(item in self.loaders for item in accepted)


class _Source:
    """The files inside a jar, a zip or a folder."""

    def __init__(self, names: Iterable[str], opener: Callable[[str], bytes]) -> None:
        self.names = set(names)
        self.open = opener

    def read(self, name: str) -> bytes | None:
        """Return a file's contents, or None if it is missing."""
        name = PurePosixPath(name.lstrip("/")).as_posix().removeprefix("./")
        return self.open(name) if name in self.names else None

    def has_folder(self, name: str) -> bool:
        """Return whether a top-level folder exists."""
        return any(item.startswith(name + "/") for item in self.names)


def _dict(value: Any) -> dict[str, Any]:
    """Return a decoded JSON or TOML table, or an empty one."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    """Return a decoded JSON or TOML array, or an empty one."""
    return cast(list[Any], value) if isinstance(value, list) else []


def _text(value: Any) -> str:
    """Flatten a string or a Minecraft text component to plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_text(item) for item in _list(value))
    part = _dict(value)
    return _text(part.get("text", "")) + _text(part.get("extra", []))


def _names(value: Any) -> tuple[str, ...]:
    """Read a list of authors given as names, objects or a comma-separated string."""
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, dict):
        return tuple(str(key) for key in _dict(value))
    names: list[str] = []
    for item in _list(value):
        if isinstance(item, str):
            names.append(item)
        elif "name" in _dict(item):
            names.append(str(_dict(item)["name"]))
    return tuple(names)


def _icon_path(value: Any) -> str | None:
    """Pick an icon path, preferring the largest when several sizes are given."""
    if isinstance(value, str):
        return value
    sizes = _dict(value)
    if sizes:
        largest = max(sizes, key=lambda key: int(key) if key.isdigit() else 0)
        return str(sizes[largest])
    return None


def _json(data: bytes) -> Any:
    """Decode JSON leniently, as mod loaders do with control characters."""
    return json.loads(data.decode("utf-8-sig"), strict=False)


def _fabric(source: _Source) -> Metadata | None:
    data = source.read("fabric.mod.json")
    if data is None:
        return None
    info = _dict(_json(data))
    icon = _icon_path(info.get("icon"))
    return Metadata(
        kind="mod",
        name=str(info.get("name") or info.get("id", "")),
        id=info.get("id"),
        version=info.get("version"),
        description=_text(info.get("description", "")),
        authors=_names(info.get("authors", [])),
        loaders=("fabric",),
        icon=source.read(icon) if icon else None,
    )


def _quilt(source: _Source) -> Metadata | None:
    data = source.read("quilt.mod.json")
    if data is None:
        return None
    loader = _dict(_dict(_json(data)).get("quilt_loader"))
    info = _dict(loader.get("metadata"))
    icon = _icon_path(info.get("icon"))
    return Metadata(
        kind="mod",
        name=str(info.get("name") or loader.get("id", "")),
        id=loader.get("id"),
        version=loader.get("version"),
        description=_text(info.get("description", "")),
        authors=_names(info.get("contributors", {})),
        loaders=("quilt",),
        icon=source.read(icon) if icon else None,
    )


def _jar_version(source: _Source) -> str | None:
    """Read ``Implementation-Version`` from the jar's manifest."""
    manifest = source.read("META-INF/MANIFEST.MF")
    for line in (manifest or b"").decode("utf-8", "replace").splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "Implementation-Version":
            return value.strip()
    return None


def _forge_toml(source: _Source, name: str, loader: str) -> Metadata | None:
    data = source.read(name)
    if data is None:
        return None
    info = tomllib.loads(data.decode("utf-8-sig"))
    mods = _list(info.get("mods"))
    mod = _dict(mods[0] if mods else None)
    if loader == "forge":
        # NeoForge's first releases kept the Forge file name.
        needs = {
            str(_dict(item).get("modId", ""))
            for items in _dict(info.get("dependencies")).values()
            for item in _list(items)
        }
        if "neoforge" in needs:
            loader = "neoforge"
    version = mod.get("version")
    if version == JAR_VERSION:
        version = _jar_version(source)
    icon = mod.get("logoFile") or info.get("logoFile")
    return Metadata(
        kind="mod",
        name=str(mod.get("displayName") or mod.get("modId", "")),
        id=mod.get("modId"),
        version=version,
        description=_text(mod.get("description", "")).strip(),
        authors=_names(mod.get("authors") or info.get("authors", [])),
        loaders=(loader,),
        icon=source.read(icon) if isinstance(icon, str) else None,
    )


def _mcmod(source: _Source) -> Metadata | None:
    data = source.read("mcmod.info")
    if data is None:
        return None
    info = _json(data)
    mods = _list(_dict(info).get("modList") if isinstance(info, dict) else info)
    mod = _dict(mods[0] if mods else None)
    icon = mod.get("logoFile")
    return Metadata(
        kind="mod",
        name=str(mod.get("name") or mod.get("modid", "")),
        id=mod.get("modid"),
        version=mod.get("version"),
        description=_text(mod.get("description", "")),
        authors=_names(mod.get("authorList", [])),
        loaders=("forge",),
        icon=source.read(icon) if isinstance(icon, str) and icon else None,
    )


def _pack(source: _Source, name: str) -> Metadata | None:
    data = source.read("pack.mcmeta")
    if data is None:
        return None
    info = _dict(_dict(_json(data)).get("pack"))
    kind: Kind = (
        "datapack"
        if source.has_folder("data") and not source.has_folder("assets")
        else "resourcepack"
    )
    pack_format = info.get("pack_format")
    return Metadata(
        kind=kind,
        name=name,
        description=_text(info.get("description", "")),
        pack_format=pack_format if isinstance(pack_format, int) else None,
        icon=source.read("pack.png"),
    )


def _describe(source: _Source, name: str) -> Metadata | None:
    """Read every declaration a source has, and merge them."""
    found: list[Metadata] = []
    readers: list[Callable[[], Metadata | None]] = [
        lambda: _fabric(source),
        lambda: _quilt(source),
        lambda: _forge_toml(source, "META-INF/neoforge.mods.toml", "neoforge"),
        lambda: _forge_toml(source, "META-INF/mods.toml", "forge"),
        lambda: _mcmod(source),
    ]
    for reader in readers:
        try:
            item = reader()
        except (ValueError, TypeError, AttributeError, IndexError, KeyError):
            # A malformed file says nothing useful; another one may.
            continue
        if item is not None:
            found.append(item)
    if found:
        # A jar built for several loaders declares itself once for each.
        loaders = tuple(dict.fromkeys(item for meta in found for item in meta.loaders))
        return replace(found[0], loaders=loaders)
    try:
        pack = _pack(source, name)
    except (ValueError, TypeError, AttributeError):
        pack = None
    if pack is not None:
        return pack
    if source.has_folder("shaders"):
        return Metadata(kind="shader", name=name)
    return None


def read(path: Path | str) -> Metadata | None:
    """Read what a mod jar, a pack archive or a pack folder declares about itself.

    Args:
        path: The jar, zip or folder.

    Returns:
        Its metadata, or None if it declares nothing this module recognises or
        is not a valid archive.

    Raises:
        OSError: The file could not be read.
    """
    path = Path(path)
    name = path.name.removesuffix(".disabled")
    for suffix in (".jar", ".zip"):
        name = name.removesuffix(suffix)
    if path.is_dir():
        files = [item for item in path.rglob("*") if item.is_file()]
        source = _Source(
            (item.relative_to(path).as_posix() for item in files),
            lambda member: (path / member).read_bytes(),
        )
        return _describe(source, name)
    try:
        with zipfile.ZipFile(path) as archive:
            source = _Source(archive.namelist(), archive.read)
            return _describe(source, name)
    except zipfile.BadZipFile:
        return None
