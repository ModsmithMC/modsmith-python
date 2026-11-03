"""Install mod loaders. Subclass `Loader` and `register` it to add another."""

from ._base import Loader, create, parse, register
from ._fabric import Fabric, MetaLoader, Quilt
from ._forge import Forge, NeoForge, ProcessorLoader

# isort: split
# Shared with other modsmith packages, but not part of the public API.
from ._base import LOADER_FALLBACKS as LOADER_FALLBACKS
from ._base import loader_name as loader_name
from ._install_profile import InstallerJar as InstallerJar
from ._install_profile import InstallProfile as InstallProfile
from ._install_profile import Library as Library
from ._install_profile import Processor as Processor

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
