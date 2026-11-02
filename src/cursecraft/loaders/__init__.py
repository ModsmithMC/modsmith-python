from ..core.settings import Settings
from .base import InstallContext, LoaderInstaller, LoaderPlan, LoaderSpec
from .fabric import FabricInstaller
from .forge_like import ForgeInstaller, NeoForgeInstaller


def build_installers(settings: Settings) -> dict[str, LoaderInstaller]:
    return {
        "forge": ForgeInstaller(settings.forge_maven_url),
        "neoforge": NeoForgeInstaller(settings.neoforge_maven_url),
        "fabric": FabricInstaller(settings.fabric_meta_url),
    }


__all__ = [
    "InstallContext",
    "LoaderInstaller",
    "LoaderPlan",
    "LoaderSpec",
    "build_installers",
]
