import json, os, shutil
from datetime import datetime, timezone
from configparser import ConfigParser
from typing import Optional, Dict

from .loaders import BaseInstaller, ForgeInstaller, FabricInstaller, NeoForgeInstaller
from .client import CurseforgeClient
from .utils import get_minecraft_dir_path, unzip_file, get_image_base64, single_download


class CurseCraft:
    def __init__(self, configs: ConfigParser, mc_root_dir: Optional[str] = None):
        self.client = CurseforgeClient(
            api_key=configs.get("CURSEFORGE", "API_KEY"),
            base_url=configs.get("CURSEFORGE", "BASE_URL"),
            game_id=configs.getint("CURSEFORGE", "MINECRAFT_GAME_ID"),
            mods_class_id=configs.getint("CURSEFORGE", "CLASS_ID.MODS"),
            modpacks_class_id=configs.getint("CURSEFORGE", "CLASS_ID.MODPACKS"),
            shaders_class_id=configs.getint("CURSEFORGE", "CLASS_ID.SHADERS"),
            bukkit_plugins_class_id=configs.getint(
                "CURSEFORGE", "CLASS_ID.BUKKIT_PLUGINS"
            ),
            addons_class_id=configs.getint("CURSEFORGE", "CLASS_ID.ADDONS"),
            worlds_class_id=configs.getint("CURSEFORGE", "CLASS_ID.WORLDS"),
            resource_packs_class_id=configs.getint(
                "CURSEFORGE", "CLASS_ID.RESOURCE_PACKS"
            ),
            customization_class_id=configs.getint(
                "CURSEFORGE", "CLASS_ID.CUSTOMIZATION"
            ),
            data_packs_class_id=configs.getint("CURSEFORGE", "CLASS_ID.DATA_PACKS"),
        )

        self.loader_installer: Dict[int, BaseInstaller] = {
            configs.getint("CURSEFORGE", "LOADER_TYPE.FORGE"): ForgeInstaller(
                maven_base_url=configs.get("MODLOADER", "BASE_URL.FORGE"),
                max_workers=configs.getint("UNIVERSAL", "MAX_WORKERS"),
            ),
            configs.getint("CURSEFORGE", "LOADER_TYPE.FABRIC"): FabricInstaller(
                meta_base_url=configs.get("MODLOADER", "BASE_URL.FABRIC"),
                max_workers=configs.getint("UNIVERSAL", "MAX_WORKERS"),
            ),
            configs.getint("CURSEFORGE", "LOADER_TYPE.NEOFORGE"): NeoForgeInstaller(
                maven_base_url=configs.get("MODLOADER", "BASE_URL.NEOFORGE"),
                max_workers=configs.getint("UNIVERSAL", "MAX_WORKERS"),
            ),
        }

        self.loader_name = {
            configs.getint("CURSEFORGE", "LOADER_TYPE.FORGE"): "forge",
            configs.getint("CURSEFORGE", "LOADER_TYPE.FABRIC"): "fabric",
            configs.getint("CURSEFORGE", "LOADER_TYPE.NEOFORGE"): "neoforge",
        }

        self.max_workers = configs.getint("UNIVERSAL", "MAX_WORKERS")
        self.block_size = configs.getint("UNIVERSAL", "BLOCK_SIZE")
        self.mc_root_dir = mc_root_dir if mc_root_dir else get_minecraft_dir_path()

    def install_modpack(
        self, mod_id: int, game_dir: Optional[str] = None, side: str = "client"
    ):
        if game_dir is None:
            game_dir = os.path.join(os.path.expanduser("~"), "Downloads")

        modpack = self.client.get_mod(mod_id)
        latest_file = sorted(
            modpack.latest_files, key=lambda x: x.file_date, reverse=True
        )[0]

        success = single_download(
            url=latest_file.download_url,
            file_name=latest_file.file_name,
            dest_path=os.path.join(game_dir, latest_file.display_name),
            block_size=self.block_size,
            expected_hash=latest_file.hashes[0].value,
            hash_algo=self.client._hash_algo[latest_file.hashes[0].algo],
        )
        if success is False:
            return False

        zip_file_name = os.path.join(
            game_dir, latest_file.display_name, latest_file.file_name
        )
        success = unzip_file(
            zip_file_name, os.path.join(game_dir, latest_file.display_name)
        )
        if success is False:
            return False

        with open(
            os.path.join(game_dir, latest_file.display_name, "manifest.json"), "r"
        ) as file:
            manifest = json.load(file)

        modpack_file_ids = [f["fileID"] for f in manifest["files"]]
        success = self.client.download_files(
            modpack_file_ids,
            os.path.join(game_dir, latest_file.display_name),
            self.block_size,
            self.max_workers,
        )
        if not all(success):
            return False

        mc_version = manifest["minecraft"]["version"]
        mod_loader_name = manifest["minecraft"]["modLoaders"][0]["id"]
        if mod_loader_name.startswith("fabric"):
            loader = self.client.get_specific_minecraft_loader(
                f"{mod_loader_name}-{mc_version}"
            )
        else:
            loader = self.client.get_specific_minecraft_loader(mod_loader_name)

        loader_version_path = os.path.join(
            self.mc_root_dir,
            "versions",
            f"{self.loader_name[loader.type]}-{loader.forge_version}",
        )

        if not (
            os.path.exists(loader_version_path)
            and os.path.exists(
                os.path.join(
                    loader_version_path,
                    f"{self.loader_name[loader.type]}-{loader.forge_version}.json",
                )
            )
        ):
            success = self.loader_installer[loader.type].install(
                mc_version, loader.forge_version, self.mc_root_dir, side
            )
            if success is False:
                return False

        with open(
            os.path.join(self.mc_root_dir, "launcher_profiles.json"), "r"
        ) as file:
            launcher_profile = json.load(file)
            launcher_profile["profiles"][modpack.slug] = {
                "gameDir": os.path.join(game_dir, latest_file.display_name),
                "icon": get_image_base64(modpack.logo.url),
                "javaArgs": f"-Xmx{manifest['minecraft'].get('recommendedRam', 2048)}M -XX:+UnlockExperimentalVMOptions -XX:+UseG1GC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M",
                "lastUsed": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "lastVersionId": f"{self.loader_name[loader.type]}-{loader.forge_version}",
                "name": modpack.name,
                "resolution": {"height": 1080, "width": 1920},
                "type": "custom",
            }

        with open(
            os.path.join(self.mc_root_dir, "launcher_profiles.json"), "w"
        ) as file:
            json.dump(launcher_profile, file, indent=2)

        overrides_dir = os.path.join(game_dir, latest_file.display_name, "overrides")
        dest_base = os.path.join(game_dir, latest_file.display_name)
        if os.path.exists(overrides_dir):
            for filename in os.listdir(overrides_dir):
                src_item = os.path.join(overrides_dir, filename)
                dest_item = os.path.join(dest_base, filename)
                if os.path.isdir(src_item):
                    if os.path.exists(dest_item):
                        shutil.copytree(src_item, dest_item, dirs_exist_ok=True)
                    else:
                        shutil.copytree(src_item, dest_item)
                else:
                    shutil.copy2(src_item, dest_item)
            shutil.rmtree(os.path.join(game_dir, latest_file.display_name, "overrides"))

        os.remove(
            os.path.join(game_dir, latest_file.display_name, latest_file.file_name)
        )
        return True
