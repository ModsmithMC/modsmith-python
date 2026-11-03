"""Mojang's version manifest and vanilla game downloads."""

from dataclasses import dataclass

from .._locks import GAME_LOCK, file_lock
from ..errors import UnsupportedError
from ..net import Resource, Session, download, session_scope
from ..progress import CancelToken, ProgressCallback
from ._game_dir import GameDir, Version

VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


@dataclass(frozen=True)
class VersionInfo:
    """One entry in Mojang's version manifest.

    Attributes:
        id: The version id.
        type: The kind of version, such as ``release`` or ``snapshot``.
        url: Where to download the version JSON.
        sha1: The version JSON's SHA-1.
        release_time: When the version was released, in ISO 8601 format.
    """

    id: str
    type: str
    url: str
    sha1: str
    release_time: str


def list_versions(
    session: Session | None = None, *, manifest_url: str = VERSION_MANIFEST_URL
) -> list[VersionInfo]:
    """List every Minecraft version Mojang publishes, newest first.

    Args:
        session: The session to use. A temporary one is created if omitted.
        manifest_url: Where to read the manifest.

    Returns:
        The manifest's entries.

    Raises:
        NetworkError: The manifest could not be fetched.
    """
    with session_scope(session) as client:
        manifest = client.get_json(manifest_url)
    return [
        VersionInfo(v["id"], v["type"], v["url"], v["sha1"], v["releaseTime"])
        for v in manifest["versions"]
    ]


def install_version(
    game: GameDir,
    version_id: str,
    *,
    session: Session | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    manifest_url: str = VERSION_MANIFEST_URL,
) -> Version:
    """Download a vanilla version's JSON and client jar into ``game``.

    Files that are already valid are kept.

    Args:
        game: The game directory.
        version_id: The Minecraft version.
        session: The session to use. A temporary one is created if omitted.
        progress: Receives updates while the client jar downloads.
        cancel: Stops the download.
        manifest_url: Where to read Mojang's version manifest.

    Returns:
        The installed version.

    Raises:
        UnsupportedError: The version is unknown or has no client download.
        NetworkError: The manifest could not be fetched.
        DownloadError: A file could not be downloaded.
        LockedError: Another install kept the game directory for too long.
        Cancelled: ``cancel`` was triggered.
    """
    lock = file_lock(game.path / GAME_LOCK, cancel=cancel)
    with lock, session_scope(session) as client:
        if not game.has_version(version_id):
            info = next(
                (
                    v
                    for v in list_versions(client, manifest_url=manifest_url)
                    if v.id == version_id
                ),
                None,
            )
            if info is None:
                raise UnsupportedError(f"Unknown Minecraft version: {version_id}")
            meta = Resource.of(
                info.url, game.version_json(version_id), {"sha1": info.sha1}
            )
            download(meta, session=client, cancel=cancel)

        version = game.version(version_id)
        if version.client_url is None:
            raise UnsupportedError(f"Version {version_id} has no client download")
        jar = Resource.of(
            version.client_url,
            game.client_jar(version_id),
            {"sha1": version.client_sha1} if version.client_sha1 else None,
            version.client_size,
        )
        download(
            jar, session=client, progress=progress, cancel=cancel, task="minecraft"
        )
    return version
