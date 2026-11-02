import os
from typing import Optional, List, Union, Dict

from .data import (
    Category,
    SearchResult,
    Mod,
    File,
    MinecraftVersion,
    ModLoader,
    MinecraftModLoader,
)
from .utils import batch_download, get, post


class CurseforgeClient:

    def __init__(
        self,
        api_key: str,
        base_url: str,
        game_id: Optional[int] = 432,
        mods_class_id: Optional[int] = 6,
        modpacks_class_id: Optional[int] = 4471,
        shaders_class_id: Optional[int] = 6552,
        bukkit_plugins_class_id: Optional[int] = 5,
        addons_class_id: Optional[int] = 4559,
        worlds_class_id: Optional[int] = 17,
        resource_packs_class_id: Optional[int] = 12,
        customization_class_id: Optional[int] = 4546,
        data_packs_class_id: Optional[int] = 6945,
    ) -> None:
        self._headers = {"Accept": "application/json", "x-api-key": api_key}
        self._base_url = base_url

        self._game_id = game_id
        self._mods_class_id = mods_class_id
        self._modpacks_class_id = modpacks_class_id
        self._shaders_class_id = shaders_class_id
        self._bukkit_plugins_class_id = bukkit_plugins_class_id
        self._addons_class_id = addons_class_id
        self._worlds_class_id = worlds_class_id
        self._resource_packs_class_id = resource_packs_class_id
        self._customization_class_id = customization_class_id
        self._data_packs_class_id = data_packs_class_id

        self._hash_algo = {1: "sha1", 2: "md5"}

    def get_categories(
        self, class_id: Optional[int] = None, class_only: Optional[bool] = None
    ) -> List[Category]:
        params = {"gameId": self._game_id, "classId": class_id, "classOnly": class_only}
        response = get(
            url=self._base_url + "/v1/categories", headers=self._headers, params=params
        ).json()
        return [Category.from_dict(category) for category in response["data"]]

    def search(
        self,
        class_id: Optional[int] = None,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        params = {
            "gameId": self._game_id,
            "classId": class_id,
            "searchFilter": search_filter,
            "sortField": sort_field,
            "sortOrder": sort_order,
            "gameVersionTypeId": game_version_type_id,
            "authorId": author_id,
            "primaryAuthorId": primary_author_id,
            "slug": slug,
            "index": index,
            "pageSize": page_size,
        }
        if category_id is not None:
            if isinstance(category_id, int):
                params["categoryId"] = category_id
            elif isinstance(category_id, list):
                params["categoryIds"] = category_id
            else:
                raise ValueError("category_id must be an int or a list of ints")

        if game_version is not None:
            if isinstance(game_version, str):
                params["gameVersion"] = game_version
            elif isinstance(game_version, list):
                params["gameVersions"] = game_version
            else:
                raise ValueError("game_version must be a str or a list of strs")

        if mod_loader_type is not None:
            if isinstance(mod_loader_type, int):
                params["modLoaderType"] = mod_loader_type
            elif isinstance(mod_loader_type, list):
                params["modLoaderTypes"] = mod_loader_type
            else:
                raise ValueError("mod_loader_type must be an int or a list of ints")

        response = get(
            url=self._base_url + "/v1/mods/search", headers=self._headers, params=params
        ).json()
        return SearchResult.from_dict(response)

    def search_mods(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._mods_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_modpacks(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._modpacks_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_shaders(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._shaders_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_bukkit_plugins(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._bukkit_plugins_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_addons(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._addons_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_worlds(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._worlds_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_resource_packs(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._resource_packs_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_customization(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._customization_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def search_data_packs(
        self,
        category_id: Optional[Union[int, List[int]]] = None,
        game_version: Optional[Union[str, List[str]]] = None,
        search_filter: Optional[str] = None,
        sort_field: Optional[int] = None,
        sort_order: Optional[str] = None,
        mod_loader_type: Optional[Union[int, List[int]]] = None,
        game_version_type_id: Optional[int] = None,
        author_id: Optional[int] = None,
        primary_author_id: Optional[int] = None,
        slug: Optional[str] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> SearchResult:
        search_params = {
            "class_id": self._data_packs_class_id,
            "category_id": category_id,
            "game_version": game_version,
            "search_filter": search_filter,
            "sort_field": sort_field,
            "sort_order": sort_order,
            "mod_loader_type": mod_loader_type,
            "game_version_type_id": game_version_type_id,
            "author_id": author_id,
            "primary_author_id": primary_author_id,
            "slug": slug,
            "index": index,
            "page_size": page_size,
        }
        return self.search(**search_params)

    def get_mod(self, mod_id: int) -> Mod:
        response = get(
            url=self._base_url + f"/v1/mods/{mod_id}", headers=self._headers
        ).json()
        return Mod.from_dict(response["data"])

    def get_mods(
        self, mod_ids: List[int], filter_pc_only: Optional[bool] = True
    ) -> List[Mod]:
        json = {"modIds": mod_ids, "filterPcOnly": filter_pc_only}
        response = post(
            url=self._base_url + "/v1/mods", headers=self._headers, json=json
        ).json()
        return [Mod.from_dict(mod) for mod in response["data"]]

    def get_featured_mods(
        self,
        excluded_mod_ids: Optional[List[int]] = None,
        game_version_type_id: Optional[int] = None,
    ) -> Dict[str, List[Mod]]:
        json = {
            "gameId": self._game_id,
            "excludedModIds": excluded_mod_ids,
            "gameVersionTypeId": game_version_type_id,
        }
        response = post(
            url=self._base_url + "/v1/mods/featured", headers=self._headers, json=json
        ).json()
        return {
            "featured": [Mod.from_dict(mod) for mod in response["data"]["featured"]],
            "popular": [Mod.from_dict(mod) for mod in response["data"]["popular"]],
            "recently updated": [
                Mod.from_dict(mod) for mod in response["data"]["recentlyUpdated"]
            ],
        }

    def get_mod_description(
        self,
        mod_id: int,
        raw: Optional[bool] = None,
        stripped: Optional[bool] = None,
        markup: Optional[bool] = None,
    ) -> str:
        params = {"raw": raw, "stripped": stripped, "markup": markup}
        response = get(
            url=self._base_url + f"/v1/mods/{mod_id}/description",
            headers=self._headers,
            params=params,
        ).json()
        return response["data"]

    def get_mod_file(self, mod_id: int, file_id: int) -> File:
        respones = get(
            url=self._base_url + f"/v1/mods/{mod_id}/files/{file_id}",
            headers=self._headers,
        ).json()
        return File.from_dict(respones["data"])

    def get_mod_files(
        self,
        mod_id: int,
        game_version: Optional[str] = None,
        mod_loader_type: Optional[int] = None,
        game_version_type_id: Optional[int] = None,
        index: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> List[File]:
        params = {
            "gameVersion": game_version,
            "modLoaderType": mod_loader_type,
            "gameVersionTypeId": game_version_type_id,
            "index": index,
            "pageSize": page_size,
        }
        response = get(
            url=self._base_url + f"/v1/mods/{mod_id}/files",
            headers=self._headers,
            params=params,
        ).json()
        return [File.from_dict(file) for file in response["data"]]

    def get_files(self, file_ids: List[int]) -> List[File]:
        json = {"fileIds": file_ids}
        response = post(
            url=self._base_url + "/v1/mods/files", headers=self._headers, json=json
        ).json()
        return [File.from_dict(file) for file in response["data"]]

    def get_mod_file_changelog(self, mod_id: int, file_id: int) -> str:
        response = get(
            url=self._base_url + f"/v1/mods/{mod_id}/files/{file_id}/changelog",
            headers=self._headers,
        ).json()
        return response["data"]

    def get_minecraft_version(
        self, sort_descending: Optional[bool] = None
    ) -> List[MinecraftVersion]:
        params = {"sortDescending": sort_descending}
        response = get(
            url=self._base_url + "/v1/minecraft/version",
            headers=self._headers,
            params=params,
        ).json()
        return [MinecraftVersion.from_dict(data) for data in response["data"]]

    def get_specific_minecraft_version(
        self, game_version_string: str
    ) -> MinecraftVersion:
        response = get(
            url=self._base_url + f"/v1/minecraft/version/{game_version_string}",
            headers=self._headers,
        ).json()
        return MinecraftVersion.from_dict(response["data"])

    def get_minecraft_loaders(
        self, game_version: Optional[str] = None, include_all: Optional[bool] = None
    ) -> List[ModLoader]:
        params = {"version": game_version, "includeAll": include_all}
        response = get(
            url=self._base_url + "/v1/minecraft/modloader",
            headers=self._headers,
            params=params,
        ).json()
        return [ModLoader.from_dict(data) for data in response["data"]]

    def get_specific_minecraft_loader(self, mod_loader_name: str) -> MinecraftModLoader:
        response = get(
            url=self._base_url + f"/v1/minecraft/modloader/{mod_loader_name}",
            headers=self._headers,
        ).json()
        return MinecraftModLoader.from_dict(response["data"])

    def download_files(
        self,
        file_ids: List[int],
        dest_path: Optional[str] = None,
        block_size: int = 8192,
        max_workers: int = 5,
    ) -> List[bool]:
        files = self.get_files(file_ids)
        mod_ids = list(set([file.mod_id for file in files]))
        mods = self.get_mods(mod_ids)

        class2folder = {
            self._mods_class_id: "mods",
            self._resource_packs_class_id: "resourcepacks",
            self._shaders_class_id: "shaderpacks",
            self._worlds_class_id: "saves",
            self._data_packs_class_id: "datapacks",
            self._bukkit_plugins_class_id: "plugins",
            self._modpacks_class_id: "modpacks",
            self._addons_class_id: "addons",
            self._customization_class_id: "config",
        }

        grouped: Dict[str, List[tuple]] = {}
        id2mod = {mod.id: mod for mod in mods}
        for file in files:
            mod = id2mod.get(file.mod_id)
            folder = class2folder.get(mod.class_id if mod else None, "other")
            grouped.setdefault(folder, []).append(
                (
                    file.file_name,
                    file.download_url,
                    file.hashes[0].value,
                    self._hash_algo[file.hashes[0].algo],
                )
            )

        results = []
        for sub_folder, urls in grouped.items():
            path = os.path.join(dest_path, sub_folder)
            os.makedirs(path, exist_ok=True)
            results.extend(batch_download(urls, path, block_size, max_workers))
        return results
