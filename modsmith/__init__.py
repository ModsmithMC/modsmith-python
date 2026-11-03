"""Modsmith: a Python toolkit for Minecraft modpacks and game files."""

import logging

from . import (
    errors,
    instances,
    java,
    launcher,
    loaders,
    metadata,
    minecraft,
    net,
    packs,
    platforms,
    progress,
)
from ._version import __version__
from .progress import CancelToken, Progress

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "CancelToken",
    "Progress",
    "__version__",
    "errors",
    "instances",
    "java",
    "launcher",
    "loaders",
    "metadata",
    "minecraft",
    "net",
    "packs",
    "platforms",
    "progress",
]
