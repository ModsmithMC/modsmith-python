from typing import Optional, Any, Dict, List
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Category:
    id: int
    name: str
    slug: str
    url: str
    icon_url: str
    date_modified: datetime
    is_class: bool
    class_id: Optional[int] = None
    display_index: Optional[int] = None
    parent_category_id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Category":
        return cls(
            id=data["id"],
            name=data["name"],
            slug=data["slug"],
            url=data["url"],
            icon_url=data["iconUrl"],
            date_modified=datetime.fromisoformat(data["dateModified"]),
            is_class=data.get("isClass", False),
            class_id=data.get("classId"),
            parent_category_id=data.get("parentCategoryId"),
            display_index=data.get("displayIndex"),
        )


@dataclass
class Links:
    website_url: Optional[str] = None
    wiki_url: Optional[str] = None
    issues_url: Optional[str] = None
    source_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Links":
        website_url = data.get("websiteUrl")
        wiki_url = data.get("wikiUrl")
        issues_url = data.get("issuesUrl")
        source_url = data.get("sourceUrl")

        return cls(
            website_url=(
                website_url if website_url is not None and website_url != "" else None
            ),
            wiki_url=wiki_url if wiki_url is not None and wiki_url != "" else None,
            issues_url=(
                issues_url if issues_url is not None and issues_url != "" else None
            ),
            source_url=(
                source_url if source_url is not None and source_url != "" else None
            ),
        )


@dataclass
class Author:
    id: int
    name: str
    url: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Author":
        return cls(id=data["id"], name=data["name"], url=data["url"])


@dataclass
class Logo:
    id: int
    mod_id: int
    title: str
    thumbnail_url: str
    url: str
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Logo":
        description = data.get("description")
        return cls(
            id=data["id"],
            mod_id=data["modId"],
            title=data["title"],
            thumbnail_url=data["thumbnailUrl"],
            url=data["url"],
            description=(
                description if description is not None and description != "" else None
            ),
        )


@dataclass
class Screenshot:
    id: int
    mod_id: int
    title: str
    thumbnail_url: str
    url: str
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Screenshot":
        description = data.get("description")
        return cls(
            id=data["id"],
            mod_id=data["modId"],
            title=data["title"],
            thumbnail_url=data["thumbnailUrl"],
            url=data["url"],
            description=(
                description if description is not None and description != "" else None
            ),
        )


@dataclass
class Hash:
    value: str
    algo: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hash":
        return cls(value=data["value"], algo=data["algo"])


@dataclass
class GameVersion:
    game_version_name: str
    game_version_padded: str
    game_version_release_date: datetime
    game_version_type_id: int
    game_version: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GameVersion":
        game_version = data.get("gameVersion")
        return cls(
            game_version_name=data["gameVersionName"],
            game_version_padded=data["gameVersionPadded"],
            game_version=(
                game_version
                if game_version is not None and game_version != ""
                else None
            ),
            game_version_release_date=datetime.fromisoformat(
                data["gameVersionReleaseDate"]
            ),
            game_version_type_id=data["gameVersionTypeId"],
        )


@dataclass
class Dependency:
    mod_id: int
    relation_type: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Dependency":
        return cls(mod_id=data["modId"], relation_type=data["relationType"])


@dataclass
class Module:
    name: str
    fingerprint: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Module":
        return cls(name=data["name"], fingerprint=data["fingerprint"])


@dataclass
class File:
    id: int
    mod_id: int
    is_available: bool
    display_name: str
    file_name: str
    release_type: int
    file_status: int
    hashes: List[Hash]
    file_date: datetime
    file_length: int
    download_count: int
    download_url: str
    game_versions: List[str]
    sortable_game_versions: List[GameVersion]
    dependencies: List[Dependency]
    alternate_file_id: int
    is_server_pack: bool
    file_fingerprint: int
    modules: Optional[List[Module]] = None
    file_size_on_disk: Optional[int] = None
    expose_as_alternative: Optional[bool] = None
    parent_project_file_id: Optional[int] = None
    server_pack_file_id: Optional[int] = None
    is_early_access_content: Optional[bool] = None
    early_access_end_date: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "File":
        expose_as_alternative = data.get("exposeAsAlternative")
        parent_project_file_id = data.get("parentProjectFileId")
        server_pack_file_id = data.get("serverPackFileId")
        is_early_access_content = data.get("isEarlyAccessContent")
        early_access_end_date_str = data.get("earlyAccessEndDate")
        download_url = data.get("downloadUrl")
        early_access_end_date = (
            datetime.fromisoformat(early_access_end_date_str)
            if early_access_end_date_str is not None and early_access_end_date_str != ""
            else None
        )

        return cls(
            id=data["id"],
            mod_id=data["modId"],
            is_available=data["isAvailable"],
            display_name=data["displayName"],
            file_name=data["fileName"],
            release_type=data["releaseType"],
            file_status=data["fileStatus"],
            hashes=[Hash.from_dict(h) for h in data["hashes"]],
            file_date=datetime.fromisoformat(data["fileDate"]),
            file_length=data["fileLength"],
            download_count=data["downloadCount"],
            file_size_on_disk=data.get("fileSizeOnDisk"),
            download_url=(
                download_url
                if download_url is not None and download_url != ""
                else f"https://edge.forgecdn.net/files/{data['id'] // 1000}/{data['id'] % 1000}/{data['fileName']}"
            ),
            game_versions=data["gameVersions"],
            sortable_game_versions=[
                GameVersion.from_dict(gv) for gv in data["sortableGameVersions"]
            ],
            dependencies=[Dependency.from_dict(d) for d in data["dependencies"]],
            alternate_file_id=data["alternateFileId"],
            is_server_pack=data["isServerPack"],
            file_fingerprint=data["fileFingerprint"],
            modules=(
                [Module.from_dict(m) for m in data["modules"]]
                if data.get("modules")
                else None
            ),
            expose_as_alternative=(
                expose_as_alternative if expose_as_alternative is not None else None
            ),
            parent_project_file_id=(
                parent_project_file_id if parent_project_file_id is not None else None
            ),
            server_pack_file_id=(
                server_pack_file_id if server_pack_file_id is not None else None
            ),
            is_early_access_content=(
                is_early_access_content
                if is_early_access_content is not None
                else False
            ),
            early_access_end_date=early_access_end_date,
        )


@dataclass
class FileIndex:
    game_version: str
    file_id: int
    file_name: str
    release_type: int
    game_version_type_id: int
    mod_loader: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileIndex":
        return cls(
            game_version=data["gameVersion"],
            file_id=data["fileId"],
            file_name=data["filename"],
            release_type=data["releaseType"],
            game_version_type_id=data["gameVersionTypeId"],
            mod_loader=data.get("modLoader"),
        )


@dataclass
class Mod:
    id: int
    name: str
    slug: str
    links: Links
    summary: str
    status: int
    download_count: int
    is_featured: bool
    primary_category_id: int
    categories: List[Category]
    class_id: int
    authors: List[Author]
    screenshots: List[Screenshot]
    main_file_id: int
    latest_files: List[File]
    latest_files_indexes: List[FileIndex]
    latest_early_access_files_indexes: List[FileIndex]
    date_created: datetime
    date_modified: datetime
    date_released: datetime
    allow_mod_distribution: bool
    game_popularity_rank: int
    is_available: bool
    thumbs_up_count: int

    logo: Optional[Logo] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Mod":
        return cls(
            id=data["id"],
            name=data["name"],
            slug=data["slug"],
            links=Links.from_dict(data["links"]),
            summary=data["summary"],
            status=data["status"],
            download_count=data["downloadCount"],
            is_featured=data["isFeatured"],
            primary_category_id=data["primaryCategoryId"],
            categories=[Category.from_dict(c) for c in data["categories"]],
            class_id=data["classId"],
            authors=[Author.from_dict(a) for a in data["authors"]],
            logo=Logo.from_dict(data["logo"]) if data.get("logo") else None,
            screenshots=[Screenshot.from_dict(s) for s in data["screenshots"]],
            main_file_id=data["mainFileId"],
            latest_files=[File.from_dict(f) for f in data["latestFiles"]],
            latest_files_indexes=[
                FileIndex.from_dict(fi) for fi in data["latestFilesIndexes"]
            ],
            latest_early_access_files_indexes=[
                FileIndex.from_dict(fi)
                for fi in data.get("latestEarlyAccessFilesIndexes", [])
            ],
            date_created=datetime.fromisoformat(data["dateCreated"]),
            date_modified=datetime.fromisoformat(data["dateModified"]),
            date_released=datetime.fromisoformat(data["dateReleased"]),
            allow_mod_distribution=data["allowModDistribution"],
            game_popularity_rank=data["gamePopularityRank"],
            is_available=data["isAvailable"],
            thumbs_up_count=data.get("thumbsUpCount", 0),
        )


@dataclass
class Pagination:
    index: int
    page_size: int
    result_count: int
    total_count: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Pagination":
        return cls(
            index=data["index"],
            page_size=data["pageSize"],
            result_count=data["resultCount"],
            total_count=data["totalCount"],
        )


@dataclass
class SearchResult:
    pagination: Pagination
    data: List[Mod]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SearchResult":
        return cls(
            pagination=Pagination.from_dict(data["pagination"]),
            data=[Mod.from_dict(m) for m in data["data"]],
        )


@dataclass
class MinecraftVersion:
    id: int
    game_version_id: int
    version_string: str
    jar_download_url: str
    json_download_url: str
    approved: bool
    date_modified: datetime
    game_version_type_id: int
    game_version_status: int
    game_version_type_status: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MinecraftVersion":
        return cls(
            id=data["id"],
            game_version_id=data["gameVersionId"],
            version_string=data["versionString"],
            jar_download_url=data["jarDownloadUrl"],
            json_download_url=data["jsonDownloadUrl"],
            approved=data["approved"],
            date_modified=datetime.fromisoformat(data["dateModified"]),
            game_version_type_id=data["gameVersionTypeId"],
            game_version_status=data["gameVersionStatus"],
            game_version_type_status=data["gameVersionTypeStatus"],
        )


@dataclass
class ModLoader:
    name: str
    game_version: str
    latest: bool
    recommended: bool
    date_modified: datetime
    type: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModLoader":
        return cls(
            name=data["name"],
            game_version=data["gameVersion"],
            latest=data["latest"],
            recommended=data["recommended"],
            date_modified=datetime.fromisoformat(data["dateModified"]),
            type=data.get("type"),
        )


@dataclass
class MinecraftModLoader:
    id: int
    game_version_id: int
    minecraft_gameVersion_id: int
    forge_version: str
    name: str
    type: int
    download_url: str
    filename: str
    install_method: int
    latest: bool
    recommended: bool
    approved: bool
    date_modified: datetime
    maven_version_string: str
    version_json: str
    libraries_install_location: str
    minecraft_version: str
    additional_files_json: str
    mod_loader_game_version_id: int
    modLoader_game_version_type_id: int
    mod_loader_game_version_status: int
    mod_loader_game_version_type_status: int
    mc_game_version_id: int
    mc_game_version_type_id: int
    mc_game_version_status: int
    mc_game_version_type_status: int
    install_profile_json: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MinecraftModLoader":
        return cls(
            id=data["id"],
            game_version_id=data["gameVersionId"],
            minecraft_gameVersion_id=data["minecraftGameVersionId"],
            forge_version=data["forgeVersion"],
            name=data["name"],
            type=data["type"],
            download_url=data.get("downloadUrl"),
            filename=data.get("filename", ""),
            install_method=data.get("installMethod", 0),
            latest=data.get("latest", False),
            recommended=data.get("recommended", False),
            approved=data.get("approved", False),
            date_modified=datetime.fromisoformat(
                data["dateModified"].replace("Z", "+00:00")
            ),
            maven_version_string=data.get("mavenVersionString", ""),
            version_json=data.get("versionJson", ""),
            libraries_install_location=data.get("librariesInstallLocation", ""),
            minecraft_version=data["minecraftVersion"],
            additional_files_json=data.get("additionalFilesJson", ""),
            mod_loader_game_version_id=data.get("modLoaderGameVersionId", 0),
            modLoader_game_version_type_id=data.get("modLoaderGameVersionTypeId", 0),
            mod_loader_game_version_status=data.get("modLoaderGameVersionStatus", 0),
            mod_loader_game_version_type_status=data.get(
                "modLoaderGameVersionTypeStatus", 0
            ),
            mc_game_version_id=data.get("mcGameVersionId", 0),
            mc_game_version_type_id=data.get("mcGameVersionTypeId", 0),
            mc_game_version_status=data.get("mcGameVersionStatus", 0),
            mc_game_version_type_status=data.get("mcGameVersionTypeStatus", 0),
            install_profile_json=data.get("installProfileJson", ""),
        )
