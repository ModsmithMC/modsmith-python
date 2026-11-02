from typing import Any

from ..core.download import DownloadTask
from ..core.events import Emit
from ..core.paths import maven_path
from ..core.steps import FunctionStep
from .base import InstallContext, LoaderPlan, LoaderSpec

DEFAULT_MAVEN_URL = "https://maven.fabricmc.net/"
HASH_FIELDS = ("sha1", "sha256", "sha512", "md5")


def library_task(library: dict[str, Any], ctx: InstallContext) -> DownloadTask:
    path = maven_path(library["name"])
    base = library.get("url") or DEFAULT_MAVEN_URL
    algo = next((name for name in HASH_FIELDS if library.get(name)), None)
    return DownloadTask(
        f"{base.rstrip('/')}/{path}",
        ctx.libraries_dir / path,
        library.get(algo) if algo else None,
        algo or "sha1",
        library.get("size"),
    )


class FabricInstaller:
    def __init__(self, meta_url: str) -> None:
        self.meta_url = meta_url.rstrip("/")

    def prepare(self, spec: LoaderSpec, ctx: InstallContext) -> LoaderPlan:
        profile = ctx.http.get_json(
            f"{self.meta_url}/v2/versions/loader/{spec.mc_version}/{spec.version}/profile/json"
        )
        version_id = profile["id"]
        if ctx.version_file(version_id).is_file():
            return LoaderPlan(version_id)

        def libraries(emit: Emit) -> None:
            tasks = [library_task(lib, ctx) for lib in profile["libraries"]]
            ctx.downloader.fetch_all(tasks, emit, "Downloading libraries")

        return LoaderPlan(
            version_id,
            [
                FunctionStep("Download fabric libraries", libraries),
                FunctionStep(
                    f"Register {version_id}",
                    lambda emit: ctx.write_version(version_id, profile),
                ),
            ],
        )
