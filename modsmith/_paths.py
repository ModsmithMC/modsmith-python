"""Internal default locations."""

from pathlib import Path

from platformdirs import user_cache_path


def default_cache_dir() -> Path:
    """Return the per-user directory used for caches by default."""
    return user_cache_path("modsmith", appauthor=False)
