"""Game directories managed from a modpack and from projects added on their own.

`Instance.sync` is both install and update: it brings a directory to the state
a pack describes, tracks what it wrote, and leaves the user's changes alone.
`Instance.plan` and `Instance.add` install single mods, resource packs and
shader packs alongside the pack, with their dependencies.
"""

from ._instance import Instance
from ._plan import Plan
from ._state import Addition, Changes, ContentFile, InstanceState

__all__ = ["Addition", "Changes", "ContentFile", "Instance", "InstanceState", "Plan"]
