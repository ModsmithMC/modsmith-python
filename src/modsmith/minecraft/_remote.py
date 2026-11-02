from dataclasses import dataclass

from ..errors import UnsupportedError
from ..net import Resource, Session, download
from ..net._session import session_scope
from ..progress import CancelToken, ProgressCallback
from ._game_dir import GameDir, Version

VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


@dataclass(frozen=True)
class VersionInfo:
    id: str
    type: str
    url: str
    sha1: str
    release_time: str


def list_versions(
    session: Session | None = None, *, manifest_url: str = VERSION_MANIFEST_URL
) -> list[VersionInfo]:
    """List every Minecraft version Mojang publishes, newest first."""
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
    """Download a vanilla version's JSON and client jar into `game`."""
    with session_scope(session) as client:
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
