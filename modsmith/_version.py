"""The installed package's version."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("modsmith")
except PackageNotFoundError:
    __version__ = "0.0.0"
