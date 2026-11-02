import base64
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.download import Downloader, DownloadTask, file_hash
from ..core.errors import (
    HttpError,
    InstanceError,
    LauncherRunningError,
    ManualDownload,
    ManualDownloadRequired,
    SourceError,
)
from ..core.events import Emit, Message, null_emit
from ..core.http import HttpClient
from ..core.settings import Settings
from ..core.steps import FunctionStep, Step, run_steps
from ..instances.store import InstanceRecord, InstanceStore
from ..launcher.detect import is_launcher_running
from ..launcher.profiles import ProfileStore
from ..loaders import InstallContext, LoaderInstaller, LoaderSpec, build_installers
from ..minecraft.java import JavaResolver
from ..minecraft.versions import VersionService
from ..sources.base import PackFile, PackManifest, Project, SearchPage, Source
from ..sources.curseforge import CurseForgeClient, CurseForgeSource
from .overrides import apply_overrides, remove_stale
from .plan import InstallPlan

PROFILE_PREFIX = "cursecraft-"
DEFAULT_SOURCE = CurseForgeSource.name
LOCAL_SOURCE = "local"


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "modpack"


def read_manifest_json(archive: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(archive) as pack:
            return json.loads(pack.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError) as e:
        raise SourceError(f"{archive.name} is not a valid modpack: {e}") from e


class CurseCraft:
    def __init__(
        self,
        settings: Settings | None = None,
        sources: dict[str, Source] | None = None,
        installers: dict[str, LoaderInstaller] | None = None,
        http: HttpClient | None = None,
    ) -> None:
        self.settings = settings or Settings.load()
        self.http = http or HttpClient()
        self.downloader = Downloader(
            self.http, self.settings.max_workers, self.settings.chunk_size
        )
        root = self.settings.minecraft_dir
        self.context = InstallContext(
            root=root,
            cache_dir=self.settings.cache_dir,
            http=self.http,
            downloader=self.downloader,
            versions=VersionService(self.http, self.downloader, root),
            java=JavaResolver(self.http, self.downloader, root, self.settings.cache_dir),
        )
        self.sources = sources or {
            DEFAULT_SOURCE: CurseForgeSource(
                CurseForgeClient(
                    self.http,
                    self.settings.curseforge_api_key,
                    self.settings.curseforge_base_url,
                )
            )
        }
        self.installers = installers or build_installers(self.settings)
        self.instances = InstanceStore(self.settings.instances_dir)
        self.profiles = ProfileStore(root)

    def search(self, text: str, source: str = DEFAULT_SOURCE, **filters: Any) -> SearchPage:
        return self.sources[source].search(text, **filters)

    def list_instances(self) -> list[InstanceRecord]:
        return self.instances.list()

    def plan_install(
        self,
        ref: str | int,
        source: str = DEFAULT_SOURCE,
        allow_prerelease: bool = False,
        emit: Emit = null_emit,
    ) -> InstallPlan:
        provider = self.sources[source]
        project = provider.get_project(ref)
        pack_file = provider.latest_pack_file(project, allow_prerelease)
        if self.instances.exists(project.slug):
            raise InstanceError(
                f"{project.slug} is already installed; update it instead"
            )
        archive = self._fetch_pack(pack_file, emit)
        return self._build_plan(provider, archive, project.slug, project, pack_file)

    def plan_local(self, archive: Path, source: str = DEFAULT_SOURCE) -> InstallPlan:
        provider = self.sources[source]
        manifest = provider.read_manifest(read_manifest_json(archive))
        slug = slugify(manifest.name)
        if self.instances.exists(slug):
            raise InstanceError(f"{slug} is already installed")
        return self._build_plan(provider, archive, slug, manifest=manifest)

    def plan_update(
        self, slug: str, allow_prerelease: bool = False, emit: Emit = null_emit
    ) -> InstallPlan | None:
        record = self.instances.load(slug)
        if record.source == LOCAL_SOURCE or record.project_id is None:
            raise InstanceError(f"{slug} was installed from a local file")
        provider = self.sources[record.source]
        project = provider.get_project(record.project_id)
        pack_file = provider.latest_pack_file(project, allow_prerelease)
        if pack_file.id == record.file_id:
            return None
        archive = self._fetch_pack(pack_file, emit)
        return self._build_plan(provider, archive, slug, project, pack_file, record)

    def _fetch_pack(self, pack_file: PackFile, emit: Emit) -> Path:
        if pack_file.url is None:
            raise SourceError(
                f"{pack_file.file_name} has no download link; import it from a local file"
            )
        dest = (
            self.settings.cache_dir
            / "packs"
            / str(pack_file.project_id)
            / str(pack_file.id)
            / pack_file.file_name
        )
        task = DownloadTask(
            pack_file.url, dest, pack_file.hash, pack_file.algo, pack_file.size
        )
        return self.downloader.fetch(task, emit)

    def _build_plan(
        self,
        provider: Source,
        archive: Path,
        slug: str,
        project: Project | None = None,
        pack_file: PackFile | None = None,
        previous: InstanceRecord | None = None,
        manifest: PackManifest | None = None,
    ) -> InstallPlan:
        manifest = manifest or provider.read_manifest(read_manifest_json(archive))
        return InstallPlan(
            source_name=provider.name if project else LOCAL_SOURCE,
            slug=slug,
            game_dir=self.instances.game_dir(slug),
            archive=archive,
            manifest=manifest,
            loader=LoaderSpec.parse(manifest.loader_id, manifest.mc_version),
            files=provider.resolve_files(manifest),
            project=project,
            pack_file=pack_file,
            previous=previous,
        )

    def install(
        self, plan: InstallPlan, emit: Emit = null_emit, force: bool = False
    ) -> InstanceRecord:
        if not force and is_launcher_running():
            raise LauncherRunningError("Close the Minecraft launcher before installing")
        self.profiles.paths()
        self._collect_manual_files(plan)

        loader = self.installers[plan.loader.kind].prepare(plan.loader, self.context)
        now = timestamp()
        previous = plan.previous
        state: dict[str, Any] = {}

        def download_files(emit: Emit) -> None:
            tasks = [
                DownloadTask(
                    file.url,
                    plan.game_dir / file.relative_path,
                    file.hash,
                    file.algo,
                    file.size,
                )
                for file in plan.files
                if file.url
            ]
            self.downloader.fetch_all(tasks, emit, "Downloading mods")

        def prepare_minecraft(emit: Emit) -> None:
            self.context.versions.ensure_client(plan.manifest.mc_version, emit)

        def overrides(emit: Emit) -> None:
            result = apply_overrides(
                plan.archive,
                plan.manifest.overrides,
                plan.game_dir,
                previous.overrides if previous else None,
            )
            state["overrides"] = result
            for relative in result.kept:
                emit(Message(f"Kept your changes to {relative}", "warning"))

        def finish(emit: Emit) -> None:
            record = self._make_record(plan, loader.version_id, state["overrides"], now)
            if previous:
                remove_stale(plan.game_dir, previous.files, record.files)
                remove_stale(plan.game_dir, previous.overrides, record.overrides)
            self._write_profile(plan, record)
            self.instances.save(record)
            state["record"] = record

        steps: list[Step] = [
            FunctionStep("Download mods", download_files),
            FunctionStep("Prepare Minecraft", prepare_minecraft),
            *loader.steps,
            FunctionStep("Apply overrides", overrides),
            FunctionStep("Register instance", finish),
        ]
        run_steps(steps, emit)
        return state["record"]

    def update(
        self, plan: InstallPlan, emit: Emit = null_emit, force: bool = False
    ) -> InstanceRecord:
        return self.install(plan, emit, force)

    def uninstall(self, slug: str, force: bool = False) -> None:
        record = self.instances.load(slug)
        if not force and is_launcher_running():
            raise LauncherRunningError("Close the Minecraft launcher before uninstalling")
        self.profiles.remove(record.profile_key)
        self.instances.delete(slug)

    def _collect_manual_files(self, plan: InstallPlan) -> None:
        missing: list[ManualDownload] = []
        for file in plan.manual_files:
            dest = plan.game_dir / file.relative_path
            task = DownloadTask("", dest, file.hash, file.algo, file.size)
            if task.is_satisfied():
                continue
            candidate = self.settings.manual_download_dir / file.file_name
            if candidate.is_file() and (
                file.hash is None or file_hash(candidate, file.algo) == file.hash.lower()
            ):
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, dest)
                continue
            missing.append(
                ManualDownload(file.file_name, file.manual_url or "", str(dest))
            )
        if missing:
            raise ManualDownloadRequired(missing)

    def _make_record(
        self, plan: InstallPlan, version_id: str, overrides: Any, now: str
    ) -> InstanceRecord:
        previous = plan.previous
        manifest = plan.manifest
        return InstanceRecord(
            slug=plan.slug,
            name=plan.project.name if plan.project else manifest.name,
            source=plan.source_name,
            project_id=plan.project.id if plan.project else None,
            file_id=plan.pack_file.id if plan.pack_file else None,
            pack_version=plan.pack_file.name if plan.pack_file else manifest.version,
            mc_version=manifest.mc_version,
            loader_id=manifest.loader_id,
            version_id=version_id,
            profile_key=PROFILE_PREFIX + plan.slug,
            files={
                file.relative_path: file_hash(plan.game_dir / file.relative_path)
                for file in plan.files
            },
            overrides=overrides.hashes,
            kept_overrides=overrides.kept,
            installed_at=previous.installed_at if previous else now,
            updated_at=now,
        )

    def _write_profile(self, plan: InstallPlan, record: InstanceRecord) -> None:
        values: dict[str, Any] = {
            "name": record.name,
            "type": "custom",
            "gameDir": str(plan.game_dir),
            "lastVersionId": record.version_id,
            "lastUsed": record.updated_at,
        }
        if not plan.previous:
            values["created"] = record.installed_at
        if plan.manifest.recommended_ram:
            values["javaArgs"] = f"-Xmx{plan.manifest.recommended_ram}M"
        icon = self._icon_data(plan.project.icon_url if plan.project else None)
        if icon:
            values["icon"] = icon
        self.profiles.upsert(record.profile_key, values)

    def _icon_data(self, url: str | None) -> str | None:
        if not url:
            return None
        try:
            response = self.http.request("GET", url)
        except HttpError:
            return None
        content_type = response.headers.get("Content-Type", "image/png").split(";")[0]
        if not content_type.startswith("image/"):
            content_type = "image/png"
        encoded = base64.b64encode(response.content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
