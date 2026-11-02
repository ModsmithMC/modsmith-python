import json
from pathlib import Path
from typing import Any

from ..core.download import Downloader, DownloadTask
from ..core.errors import UnsupportedError
from ..core.events import Emit, null_emit
from ..core.http import HttpClient

VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
LEGACY_JAVA_COMPONENT = "jre-legacy"


class VersionService:
    def __init__(self, http: HttpClient, downloader: Downloader, root: Path) -> None:
        self.http = http
        self.downloader = downloader
        self.root = root
        self._manifest: dict[str, Any] | None = None

    def version_file(self, version: str) -> Path:
        return self.root / "versions" / version / f"{version}.json"

    def client_jar(self, version: str) -> Path:
        return self.root / "versions" / version / f"{version}.jar"

    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            self._manifest = self.http.get_json(VERSION_MANIFEST_URL)
        return self._manifest

    def metadata(self, version: str, emit: Emit = null_emit) -> dict[str, Any]:
        path = self.version_file(version)
        if not path.is_file():
            entry = next(
                (v for v in self.manifest()["versions"] if v["id"] == version), None
            )
            if entry is None:
                raise UnsupportedError(f"Unknown Minecraft version: {version}")
            self.downloader.fetch(DownloadTask(entry["url"], path, entry["sha1"]), emit)
        return json.loads(path.read_text(encoding="utf-8"))

    def ensure_client(self, version: str, emit: Emit = null_emit) -> Path:
        client = self.metadata(version, emit)["downloads"]["client"]
        task = DownloadTask(
            client["url"], self.client_jar(version), client["sha1"], size=client["size"]
        )
        return self.downloader.fetch(task, emit)

    def java_component(self, version: str) -> str:
        java = self.metadata(version).get("javaVersion") or {}
        return java.get("component", LEGACY_JAVA_COMPONENT)
