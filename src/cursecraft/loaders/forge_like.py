import tempfile
from pathlib import Path

from ..core.download import DownloadTask
from ..core.errors import HttpError, JavaNotFoundError, ProcessorError
from ..core.events import Emit, Message
from ..core.steps import FunctionStep
from .base import InstallContext, LoaderPlan, LoaderSpec
from .install_profile import InstallerJar, Library, Variables
from .processors import run_processors


class ForgeLikeInstaller:
    def __init__(self, maven_url: str) -> None:
        self.maven_url = maven_url.rstrip("/")

    def installer_url(self, spec: LoaderSpec) -> str:
        raise NotImplementedError

    def _fetch_installer(self, spec: LoaderSpec, ctx: InstallContext) -> InstallerJar:
        url = self.installer_url(spec)
        dest = ctx.cache_dir / "installers" / url.rsplit("/", 1)[1]
        if not dest.is_file():
            try:
                sha1 = ctx.http.request("GET", f"{url}.sha1").text.split()[0].lower()
            except (HttpError, IndexError):
                sha1 = None
            ctx.downloader.fetch(DownloadTask(url, dest, sha1))
        return InstallerJar(dest)

    def prepare(self, spec: LoaderSpec, ctx: InstallContext) -> LoaderPlan:
        installer = self._fetch_installer(spec, ctx)
        version_id = installer.version_json["id"]
        if ctx.version_file(version_id).is_file():
            return LoaderPlan(version_id)
        return LoaderPlan(
            version_id,
            [
                FunctionStep(
                    f"Download {spec.kind} libraries",
                    lambda emit: self._install_libraries(installer, ctx, emit),
                ),
                FunctionStep(
                    f"Patch Minecraft for {spec.kind}",
                    lambda emit: self._patch(installer, ctx, emit),
                ),
                FunctionStep(
                    f"Register {version_id}",
                    lambda emit: ctx.write_version(version_id, installer.version_json),
                ),
            ],
        )

    def _library_task(self, library: Library, ctx: InstallContext) -> DownloadTask | None:
        dest = ctx.libraries_dir / library.path
        url = library.url or f"{self.maven_url}/{library.path}"
        if not library.url and dest.is_file():
            return None
        return DownloadTask(url, dest, library.sha1, size=library.size)

    def _install_libraries(
        self, installer: InstallerJar, ctx: InstallContext, emit: Emit
    ) -> None:
        installer.extract_bundled_libraries(ctx.libraries_dir)
        version_libraries = [
            Library.from_dict(lib) for lib in installer.version_json.get("libraries", [])
        ]
        tasks = [
            self._library_task(library, ctx)
            for library in [*installer.profile.libraries, *version_libraries]
        ]
        ctx.downloader.fetch_all(filter(None, tasks), emit, "Downloading libraries")

    def _patch(self, installer: InstallerJar, ctx: InstallContext, emit: Emit) -> None:
        processors = installer.profile.client_processors()
        if not processors:
            return
        minecraft = installer.profile.minecraft
        client_jar = ctx.versions.ensure_client(minecraft, emit)
        component = ctx.versions.java_component(minecraft)

        with tempfile.TemporaryDirectory(prefix="cursecraft-installer-") as temp:
            variables = Variables.build(
                installer, ctx.libraries_dir, ctx.root, client_jar, Path(temp)
            )

            def attempt(java: Path) -> None:
                run_processors(processors, variables, java, ctx.libraries_dir, emit)

            failure: ProcessorError | None = None
            for java in ctx.java.candidates(component):
                try:
                    attempt(java)
                    return
                except ProcessorError as e:
                    failure = e
                    emit(Message(f"Processors failed with {java}: {e}", "warning"))
            if ctx.java.find(component):
                raise failure
            try:
                java = ctx.java.download(component, emit)
            except JavaNotFoundError as e:
                raise (failure or e) from e
            attempt(java)


class ForgeInstaller(ForgeLikeInstaller):
    def installer_url(self, spec: LoaderSpec) -> str:
        version = f"{spec.mc_version}-{spec.version}"
        return f"{self.maven_url}/net/minecraftforge/forge/{version}/forge-{version}-installer.jar"


class NeoForgeInstaller(ForgeLikeInstaller):
    LEGACY_MC_VERSION = "1.20.1"

    def installer_url(self, spec: LoaderSpec) -> str:
        if spec.mc_version == self.LEGACY_MC_VERSION:
            version = f"{spec.mc_version}-{spec.version}"
            return f"{self.maven_url}/net/neoforged/forge/{version}/forge-{version}-installer.jar"
        return f"{self.maven_url}/net/neoforged/neoforge/{spec.version}/neoforge-{spec.version}-installer.jar"
