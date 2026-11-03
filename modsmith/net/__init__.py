"""HTTP access and verified, resumable downloads."""

from ._download import download
from ._resource import Resource, file_hash
from ._session import Session

# isort: split
# Shared with other modsmith packages, but not part of the public API.
from ._resource import matches as matches
from ._resource import stream_hash as stream_hash
from ._resource import strongest_hash as strongest_hash
from ._session import DEFAULT_USER_AGENT as DEFAULT_USER_AGENT
from ._session import session_scope as session_scope

__all__ = ["Resource", "Session", "download", "file_hash"]
