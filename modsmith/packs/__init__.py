"""Read modpack archives. `load` detects the format from the archive."""

from ._formats import CurseForgePack, Mrpack, PackFormat, load, register
from ._model import FileRef, Modpack, PackEntry, Side, Support, safe_relative

__all__ = [
    "CurseForgePack",
    "FileRef",
    "Modpack",
    "Mrpack",
    "PackEntry",
    "PackFormat",
    "Side",
    "Support",
    "load",
    "register",
    "safe_relative",
]
