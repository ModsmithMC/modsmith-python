"""Install mod loaders. Subclass `Loader` and `register` it to add another."""

from ._base import (
    Loader,
    LoaderVersion,
    create,
    parse,
    recommended,
    register,
    versions,
)
from ._fabric import Fabric, MetaLoader, Quilt
from ._forge import Forge, NeoForge, ProcessorLoader

__all__ = [
    "Fabric",
    "Forge",
    "Loader",
    "LoaderVersion",
    "MetaLoader",
    "NeoForge",
    "ProcessorLoader",
    "Quilt",
    "create",
    "parse",
    "recommended",
    "register",
    "versions",
]
