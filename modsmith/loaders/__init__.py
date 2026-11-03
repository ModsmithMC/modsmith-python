"""Install mod loaders. Subclass `Loader` and `register` it to add another."""

from ._base import Loader, create, parse, register
from ._fabric import Fabric, MetaLoader, Quilt
from ._forge import Forge, NeoForge, ProcessorLoader

__all__ = [
    "Fabric",
    "Forge",
    "Loader",
    "MetaLoader",
    "NeoForge",
    "ProcessorLoader",
    "Quilt",
    "create",
    "parse",
    "register",
]
