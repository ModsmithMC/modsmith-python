import json, zipfile, io, re, tempfile, os, subprocess
from typing import Dict, Any, Tuple, Optional, List

from .utils import (
    resolve_maven_coord,
    batch_download,
    get,
    single_download,
    universal_headers,
    get_main_class,
    hash_verify,
    get_minecraft_dir_path,
    request,
)


class BaseInstaller:
    def __init__(self, api_base_url: str, max_workers: int = 5, block_size: int = 8192):
        self._headers = universal_headers
        self._base_url = api_base_url
        self._max_workers = max_workers
        self._block_size = block_size

        self._installer = {}
        self._static_data = {}

        self._pattern = re.compile(r"(\{[A-Z_]+\})|(\[[^\]]+\])")

    def _get_installer(self, url: str) -> None:
        response = get(url)
        try:
            with zipfile.ZipFile(io.BytesIO(response.content), "r") as zip_ref:
                for file_name in zip_ref.namelist():
                    if file_name.endswith("/"):
                        continue
                    self._installer[file_name] = zip_ref.read(file_name)
        except Exception as e:
            raise RuntimeError(f"解析 installer 失败: {e}")

    def _replace_arg_variable(self, arg: str) -> str:
        def replace_match(match):
            var_match = match.group(1)
            maven_match = match.group(2)

            if var_match:
                key = var_match[1:-1]
                if key in self._static_data:
                    return self._static_data[key]
                else:
                    return var_match

            elif maven_match:
                coord = maven_match[1:-1]
                try:
                    resolved_path = resolve_maven_coord(coord)
                    resolved_path = os.path.join(
                        self._static_data["ROOT"], "libraries", resolved_path
                    )
                    return resolved_path
                except Exception as e:
                    print(f"Error resolving maven coord {coord}: {e}")
                    return maven_match

            return match.group(0)

        return self._pattern.sub(replace_match, arg)

    def _parse_install_profile(self, install_profile: Dict[str, Any], side: str):
        for key, values in install_profile["data"].items():
            self._static_data[key] = self._replace_arg_variable(values[side])
        processors = []
        for processor in install_profile["processors"]:
            if self._static_data["SIDE"] not in processor.get("sides", [side]):
                continue

            jar_path = os.path.join(
                self._static_data["ROOT"],
                "libraries",
                resolve_maven_coord(processor["jar"]),
            )

            main_class = get_main_class(jar_path)

            class_paths = []
            for class_coord in processor.get("classpath"):
                class_path = os.path.join(
                    self._static_data["ROOT"],
                    "libraries",
                    resolve_maven_coord(class_coord),
                )
                class_paths.append(class_path)
            if jar_path not in class_paths:
                class_paths.insert(0, jar_path)
            args = []
            for arg in processor["args"]:
                arg = self._replace_arg_variable(arg)
                args.append(arg)

            outputs = {}
            if processor.get("outputs") is not None:
                for key, value in processor.get("outputs").items():
                    outputs[self._replace_arg_variable(key)] = (
                        self._replace_arg_variable(value)
                    )

            processors.append(
                {
                    "jar": jar_path,
                    "main_class": main_class,
                    "class_paths": class_paths,
                    "args": args,
                    "outputs": outputs,
                }
            )
        return processors

    def _run_processors(
        self, processors: Dict[str, Any], java_executable: str = "java"
    ) -> List[bool]:
        def single_process(
            processor: Dict[str, Any],
            java_executable: str = "java",
        ) -> bool:
            main_class = processor.get("main_class")
            class_paths = processor.get("class_paths")
            args = processor["args"]
            outputs = processor.get("outputs")

            temp_files = []
            for i, arg in enumerate(args):
                if arg.startswith("/data/"):
                    file_key = arg[1:]
                    file_bytes = self._installer[file_key]

                    temp_file = tempfile.NamedTemporaryFile(
                        delete=False, suffix=os.path.basename(file_key)
                    )
                    temp_file.write(file_bytes)
                    temp_file.close()

                    temp_files.append(temp_file.name)
                    args[i] = temp_file.name

            classpath_str = os.pathsep.join(class_paths)
            command = [java_executable, "-cp", classpath_str, main_class] + args
            try:
                result = subprocess.run(
                    command,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                print(result.stdout)
                if not outputs:
                    for file_path, hash_value in outputs.keys():
                        hash_verify(file_path, hash_value, "sha1")
                return True
            except subprocess.CalledProcessError as e:
                print(f"Fail to patch, Return Code: {e.returncode}")
                print(f"Stdout: {e.stdout}")
                print(f"Stderr: {e.stderr}")
                return False
            except Exception as e:
                print(f"Fail to patch: {e}")
                return False
            finally:
                for temp_file_path in temp_files:
                    try:
                        os.remove(temp_file_path)
                    except OSError:
                        pass

        results = []
        for processor in processors:
            results.append(single_process(processor, java_executable))
        return results

    def _install_initialize(
        self,
        install_side: str,
        minecraft_version: str,
        loader_name: str,
        loader_version: str,
        install_path: Optional[str] = None,
    ) -> None:
        self._static_data["SIDE"] = install_side
        self._static_data["ROOT"] = (
            install_path if install_path else get_minecraft_dir_path()
        )
        self._static_data["MINECRAFT_VERSION"] = minecraft_version
        self._static_data["LOADER_NAME"] = loader_name
        self._static_data["LOADER_VERSION"] = loader_version
        self._static_data["MINECRAFT_JAR"] = os.path.join(
            self._static_data["ROOT"],
            "versions",
            minecraft_version,
            f"{minecraft_version}.jar",
        )

    def _write_version_file(self, data: Dict[str, Any]) -> bool:
        file_path = os.path.join(
            self._static_data["ROOT"],
            "versions",
            f"{self._static_data["LOADER_NAME"]}-{self._static_data["LOADER_VERSION"]}",
        )
        file_name = os.path.join(
            file_path,
            f"{self._static_data["LOADER_NAME"]}-{self._static_data["LOADER_VERSION"]}.json",
        )
        data["id"] = (
            f"{self._static_data["LOADER_NAME"]}-{self._static_data["LOADER_VERSION"]}"
        )
        try:
            os.makedirs(file_path, exist_ok=True)
            with open(file_name, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"写入配置文件失败: {e}")
            return False
        return True

    def check_and_download_minecraft_jar(self) -> bool:
        if os.path.exists(self._static_data["MINECRAFT_JAR"]) is False:
            manifest = request(
                "GET", "https://launchermeta.mojang.com/mc/game/version_manifest.json"
            ).json()
            target_version = None
            for version_info in manifest["versions"]:
                if version_info["id"] == self._static_data["MINECRAFT_VERSION"]:
                    target_version = version_info
                    break
            version_data = request("GET", target_version["url"]).json()
            return single_download(
                version_data["downloads"]["client"]["url"],
                f"{self._static_data["MINECRAFT_VERSION"]}.jar",
                os.path.join(
                    self._static_data["ROOT"],
                    "versions",
                    self._static_data["MINECRAFT_VERSION"],
                ),
                self._block_size,
                version_data["downloads"]["client"]["sha1"],
                "sha1",
            )
        return True

    def install(
        self,
        minecraft_version: str,
        loader_version: str,
        minecraft_dir_path: Optional[str] = None,
        install_side: str = "client",
    ):
        raise NotImplementedError("Not implemented yet.")


class ForgeInstaller(BaseInstaller):
    def __init__(
        self, maven_base_url="https://maven.minecraftforge.net", max_workers=5
    ) -> None:
        super(ForgeInstaller, self).__init__(maven_base_url, max_workers)

    def install(
        self,
        minecraft_version,
        loader_version,
        minecraft_dir_path=None,
        install_side="client",
    ) -> bool:
        self._install_initialize(
            install_side,
            minecraft_version,
            "forge",
            loader_version,
            minecraft_dir_path,
        )
        self._get_installer(
            self._base_url
            + f"/net/minecraftforge/forge/{minecraft_version}-{loader_version}/forge-{minecraft_version}-{loader_version}-installer.jar"
        )
        install_profile = json.loads(self._installer["install_profile.json"])
        version_profile = json.loads(self._installer["version.json"])

        grouped_tasks: Dict[str, List[str]] = {}
        for lib in install_profile["libraries"]:
            sha1_value = lib["downloads"]["artifact"]["sha1"]
            folder_prefix = os.path.dirname(lib["downloads"]["artifact"]["path"])
            file_name = os.path.basename(lib["downloads"]["artifact"]["path"])
            download_url = (
                lib["downloads"]["artifact"]["url"]
                if lib["downloads"]["artifact"]["url"]
                and lib["downloads"]["artifact"]["url"] != ""
                else f"{self._base_url}/{resolve_maven_coord(lib["name"])}"
            )
            task = (file_name, download_url, sha1_value, "sha1")
            grouped_tasks.setdefault(folder_prefix, []).append(task)

        deps_res = []
        for prefix, tasks in grouped_tasks.items():
            path = os.path.join(self._static_data["ROOT"], "libraries", prefix)
            deps_res.extend(
                batch_download(tasks, path, self._block_size, self._max_workers)
            )
        if not all(deps_res):
            return False

        self.check_and_download_minecraft_jar()
        processors = self._parse_install_profile(install_profile, install_side)
        pro_res = self._run_processors(processors)
        if not all(pro_res):
            return False

        return self._write_version_file(version_profile)


class FabricInstaller(BaseInstaller):
    def __init__(
        self, meta_base_url="https://meta.fabricmc.net", max_workers=5
    ) -> None:
        super(FabricInstaller, self).__init__(meta_base_url, max_workers)

    def _get_lib_hash(self, data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        if data.get("sha1") is not None:
            return data.get("sha1"), "sha1"
        elif data.get("md5") is not None:
            return data.get("md5"), "md5"
        elif data.get("sha256") is not None:
            return data.get("sha256"), "sha256"
        elif data.get("sha512") is not None:
            return data.get("sha512"), "sha512"
        else:
            return None

    def install(
        self,
        minecraft_version,
        loader_version,
        minecraft_dir_path=None,
        install_side="client",
    ):
        self._install_initialize(
            install_side,
            minecraft_version,
            "fabric",
            loader_version,
            minecraft_dir_path,
        )

        version_profile = get(
            self._base_url
            + f"/v2/versions/loader/{minecraft_version}/{loader_version}/profile/json"
        ).json()
        libraries = version_profile["libraries"]

        grouped_tasks: Dict[str, List[str]] = {}
        for lib in libraries:
            hash_pack = self._get_lib_hash(lib)
            maven_path = resolve_maven_coord(lib.get("name"))
            url = lib.get("url") + maven_path
            folder_prefix = os.path.dirname(maven_path)
            file_name = os.path.basename(maven_path)
            if hash_pack is not None:
                task = (file_name, url, hash_pack[0], hash_pack[1])
            else:
                task = (file_name, url)
            grouped_tasks.setdefault(folder_prefix, []).append(task)

        deps_res = []
        for prefix, tasks in grouped_tasks.items():
            path = os.path.join(self._static_data["ROOT"], "libraries", prefix)
            deps_res.extend(
                batch_download(tasks, path, self._block_size, self._max_workers)
            )
        if all(deps_res) is not True:
            return False

        return self._write_version_file(version_profile)


class NeoForgeInstaller(BaseInstaller):
    def __init__(
        self, maven_base_url="https://maven.neoforged.net", max_workers=5
    ) -> None:
        super(NeoForgeInstaller, self).__init__(maven_base_url, max_workers)

    def install(
        self,
        minecraft_version,
        loader_version,
        minecraft_dir_path=None,
        install_side="client",
    ):
        self._install_initialize(
            install_side,
            minecraft_version,
            "neoforge",
            loader_version,
            minecraft_dir_path,
        )
        self._get_installer(
            self._base_url
            + f"/releases/net/neoforged/neoforge/{loader_version}/neoforge-{loader_version}-installer.jar"
        )

        install_profile = json.loads(self._installer["install_profile.json"])
        version_profile = json.loads(self._installer["version.json"])

        grouped_tasks: Dict[str, List[str]] = {}
        for lib in install_profile["libraries"]:
            sha1_value = lib["downloads"]["artifact"]["sha1"]
            folder_prefix = os.path.dirname(lib["downloads"]["artifact"]["path"])
            file_name = os.path.basename(lib["downloads"]["artifact"]["path"])
            task = (file_name, lib["downloads"]["artifact"]["url"], sha1_value, "sha1")
            grouped_tasks.setdefault(folder_prefix, []).append(task)

        deps_res = []
        for prefix, tasks in grouped_tasks.items():
            path = os.path.join(self._static_data["ROOT"], "libraries", prefix)
            deps_res.extend(
                batch_download(tasks, path, self._block_size, self._max_workers)
            )
        if not all(deps_res):
            return False

        self.check_and_download_minecraft_jar()
        processors = self._parse_install_profile(install_profile, install_side)
        pro_res = self._run_processors(processors)
        if not all(pro_res):
            return False

        return self._write_version_file(version_profile)


class QuiltInstaller(BaseInstaller):
    def __init__(
        self, maven_base_url="https://maven.quiltmc.org", max_workers=5
    ) -> None:
        super(QuiltInstaller, self).__init__(maven_base_url, max_workers)

    def install(
        self,
        minecraft_version,
        loader_version,
        minecraft_dir_path=None,
        install_side="client",
    ):
        return super().install(
            minecraft_version,
            loader_version,
            minecraft_dir_path,
            install_side,
        )
