"""Install mod loaders. Subclass `Loader` and `register` it to add another."""

from ._base import Loader, create, parse, register
from ._fabric import Fabric, MetaLoader, Quilt
from ._forge import Forge, NeoForge, ProcessorLoader
from ._install_profile import InstallerJar, InstallProfile, Library, Processor

__all__ = [
    "Fabric",
    "Forge",
    "InstallProfile",
    "InstallerJar",
    "Library",
    "Loader",
    "MetaLoader",
    "NeoForge",
    "Processor",
    "ProcessorLoader",
    "Quilt",
    "create",
    "parse",
    "register",
]
