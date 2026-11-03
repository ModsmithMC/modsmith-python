"""The CurseForge platform."""

import dataclasses
import re
from collections.abc import Iterable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ..errors import NetworkError, PlatformError
from ..net import Session
from ..packs import Modpack, PackEntry
from ..progress import CancelToken, ProgressCallback
from ._base import (
    GAME_VERSION,
    Dependency,
    DependencyKind,
    Platform,
    Project,
    ProjectType,
    Release,
    ReleaseFile,
    ReleaseType,
    SearchResults,
    SearchSort,
    collect_pages,
    digest_files,
    project_ref,
    release_versions,
)
from ._fingerprint import fingerprint

API_URL = "https://api.curseforge.com"
# Minecraft's id on CurseForge.
GAME_ID = 432
# The most ids to send in one request.
BATCH_SIZE = 500
PAGE_SIZE = 50
# CurseForge rejects requests where index + pageSize is larger than this.
MAX_RESULTS = 10000
# CurseForge's numeric ids for hash algorithms, release types and categories.
HASH_ALGORITHMS = {1: "sha1", 2: "md5"}
RELEASE_TYPES: dict[int, ReleaseType] = {1: "release", 2: "beta", 3: "alpha"}
RELATION_KINDS: dict[int, DependencyKind] = {
    1: "embedded",  # EmbeddedLibrary
    2: "optional",  # OptionalDependency
    3: "required",  # RequiredDependency
    4: "optional",  # Tool
    5: "incompatible",  # Incompatible
    6: "embedded",  # Include
}
PROJECT_CLASSES: dict[str, int] = {
    "mod": 6,
    "modpack": 4471,
    "resourcepack": 12,
    "shader": 6552,
}
CLASS_TYPES = {class_id: kind for kind, class_id in PROJECT_CLASSES.items()}
CLASS_FOLDERS = {
    6: "mods",
    12: "resourcepacks",
    17: "saves",
    4546: "config",
    6552: "shaderpacks",
    6945: "datapacks",
}
LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
# CurseForge's sort fields. It has no relevance order, and without a sort
# field results come back in no useful order, so popularity stands in.
SORT_FIELDS: dict[str, int] = {
    "relevance": 2,
    "popularity": 2,
    "updated": 3,
    "downloads": 6,
    "newest": 11,
}
SEARCH_PAGE = 50
# CurseForge refuses to page past this many results.
SEARCH_REACH = 10_000


# HTML tags that start a new line in plain text.
BLOCK_TAGS = frozenset(
    {
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "ol",
        "p",
        "pre",
        "tr",
        "ul",
    }
)


class _PlainText(HTMLParser):
    """Collects an HTML fragment's text, keeping its line structure."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Start a line, or a list item, where the tag begins one."""
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """End the line where a block ends."""
        if tag in BLOCK_TAGS or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        """Keep text, with HTML's whitespace rules: any run of it is one space."""
        self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    """Turn a changelog's HTML into plain text, with lists as ``-`` lines."""
    parser = _PlainText()
    parser.feed(html)
    parser.close()
    lines: list[str] = []
    for raw in "".join(parser.parts).splitlines():
        line = " ".join(raw.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


def split_versions(labels: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a file's version labels into game versions and mod loaders.

    CurseForge puts both in one list, along with labels such as ``Client``,
    ``Server`` and ``Beta 1.7.3``, which are left out.

    Returns:
        The game versions, and the loaders under the names the rest of the
        library uses, such as ``neoforge``.
    """
    labels = list(labels)
    games = tuple(label for label in labels if GAME_VERSION.match(label))
    loaders = (label.lower() for label in labels if label.lower() in LOADER_TYPES)
    return games, tuple(dict.fromkeys(loaders))


class _Schema(BaseModel):
    """Base for CurseForge API models, which use camelCase names."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        alias_generator=to_camel, populate_by_name=True
    )


class _Hash(_Schema):
    """A file hash from the CurseForge API."""

    value: str
    algo: int


class _Dependency(_Schema):
    """A file's dependency from the CurseForge API."""

    mod_id: int
    relation_type: int


class _File(_Schema):
    """A file from the CurseForge API."""

    id: int
    mod_id: int
    display_name: str = ""
    file_name: str
    release_type: Literal[1, 2, 3] = 1
    file_date: str = ""
    file_length: int | None = None
    download_url: str | None = None
    hashes: list[_Hash] = Field(default_factory=list[_Hash])
    is_server_pack: bool | None = False
    game_versions: list[str] = Field(default_factory=list[str])
    dependencies: list[_Dependency] = Field(default_factory=list[_Dependency])
    file_fingerprint: int | None = None

    @property
    def hash_map(self) -> dict[str, str]:
        """The digests keyed by algorithm name."""
        return {
            HASH_ALGORITHMS[item.algo]: item.value
            for item in self.hashes
            if item.algo in HASH_ALGORITHMS
        }

    def to_release(self, platform: str) -> Release:
        """Convert this file to a `Release`."""
        urls = (self.download_url,) if self.download_url else ()
        games, loaders = split_versions(self.game_versions)
        return Release(
            platform=platform,
            id=str(self.id),
            project_id=str(self.mod_id),
            name=self.display_name or self.file_name,
            release_type=RELEASE_TYPES[self.release_type],
            published=self.file_date,
            game_versions=games,
            loaders=loaders,
            files=(ReleaseFile(self.file_name, urls, self.hash_map, self.file_length),),
            dependencies=tuple(
                Dependency(RELATION_KINDS[item.relation_type], str(item.mod_id))
                for item in self.dependencies
                if item.relation_type in RELATION_KINDS
            ),
        )


class _Logo(_Schema):
    """A project's logo from the CurseForge API."""

    url: str | None = None
    thumbnail_url: str | None = None


class _Links(_Schema):
    """A project's links from the CurseForge API."""

    website_url: str | None = None


class _Named(_Schema):
    """An author or a category from the CurseForge API."""

    name: str


class _FileIndex(_Schema):
    """An entry of a project's latest files from the CurseForge API."""

    game_version: str = ""


class _Mod(_Schema):
    """A project from the CurseForge API."""

    id: int
    name: str
    slug: str
    summary: str = ""
    class_id: int | None = None
    logo: _Logo | None = None
    links: _Links | None = None
    allow_mod_distribution: bool | None = None
    download_count: int = 0
    authors: list[_Named] = Field(default_factory=list[_Named])
    categories: list[_Named] = Field(default_factory=list[_Named])
    date_modified: str = ""
    favorite_count: int = 0
    latest_files_indexes: list[_FileIndex] = Field(default_factory=list[_FileIndex])

    def to_project(self, platform: str, project_type: str) -> Project:
        """Convert this mod to a `Project`, preferring the type CurseForge reports."""
        logo = self.logo
        return Project(
            platform=platform,
            id=str(self.id),
            slug=self.slug,
            name=self.name,
            summary=self.summary,
            project_type=CLASS_TYPES.get(self.class_id or 0, project_type),
            icon_url=(logo.thumbnail_url or logo.url) if logo else None,
            url=self.links.website_url if self.links else None,
            downloads=self.download_count,
            author=self.authors[0].name if self.authors else None,
            categories=tuple(dict.fromkeys(item.name for item in self.categories)),
            updated=self.date_modified,
            follows=self.favorite_count,
            game_versions=release_versions(
                item.game_version for item in self.latest_files_indexes
            ),
        )


class CurseForge(Platform):
    """CurseForge. Requires an API key from console.curseforge.com.

    Args:
        api_key: The API key.
        session: The session to use. If omitted, the platform creates its own.
        base_url: The API's base URL.

    Attributes:
        api_key: The API key.
        base_url: The API's base URL.

    Raises:
        PlatformError: The API key is empty.
    """

    name: ClassVar[str] = "curseforge"

    def __init__(
        self,
        api_key: str,
        *,
        session: Session | None = None,
        base_url: str = API_URL,
    ) -> None:
        super().__init__(session)
        if not api_key:
            raise PlatformError("CurseForge requires an API key")
        self.api_key = api_key
        self.base_url: str = base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        """The headers sent with every request."""
        return {"Accept": "application/json", "x-api-key": self.api_key}

    def _get(self, path: str, **params: Any) -> Any:
        """Send a GET request to the API."""
        return self.session.get_json(
            self.base_url + path, headers=self._headers, params=params
        )

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        """Send a POST request to the API."""
        return self.session.post_json(
            self.base_url + path, headers=self._headers, json=payload
        )

    def _search(self, project_type: str, **params: Any) -> Any:
        """Search the Minecraft projects of one type."""
        return self._get(
            "/v1/mods/search",
            gameId=GAME_ID,
            classId=PROJECT_CLASSES[project_type],
            **params,
        )

    def search(
        self,
        query: str,
        *,
        project_type: ProjectType = "modpack",
        game_version: str | None = None,
        loader: str | None = None,
        sort: SearchSort = "relevance",
        offset: int = 0,
        limit: int = 20,
    ) -> SearchResults:
        """Search CurseForge's catalogue.

        CurseForge has no relevance order, so ``relevance`` lists the most
        popular matches first. It serves 50 results a page and no more than
        10,000 in all; larger limits read several pages, up to that depth.

        Args:
            query: The search text.
            project_type: The kind of project to find.
            game_version: Only match this Minecraft version.
            loader: Only match this mod loader.
            sort: How to order the results.
            offset: How many results to skip.
            limit: The maximum number of results to return.

        Returns:
            The results.

        Raises:
            NetworkError: CurseForge could not be reached.
        """

        def page(start: int, size: int) -> tuple[list[Project], int]:
            data = self._search(
                project_type,
                searchFilter=query,
                sortField=SORT_FIELDS[sort],
                sortOrder="desc",
                gameVersion=game_version,
                modLoaderType=LOADER_TYPES.get(loader or ""),
                index=start,
                pageSize=size,
            )
            mods = [_Mod.model_validate(item) for item in data["data"]]
            pagination: dict[str, Any] = data.get("pagination") or {}
            total = pagination.get("totalCount", len(mods))
            return [mod.to_project(self.name, project_type) for mod in mods], total

        return collect_pages(page, offset, limit, SEARCH_PAGE, SEARCH_REACH)

    def changelog(self, release: Release) -> str:
        """Return what changed in a release, converted from CurseForge's HTML.

        Args:
            release: The release.

        Returns:
            The changelog as plain text, with list items as ``-`` lines, or an
            empty string if there is none.

        Raises:
            NetworkError: CurseForge could not be reached or does not know it.
        """
        path = f"/v1/mods/{release.project_id}/files/{release.id}/changelog"
        return html_to_text(str(self._get(path).get("data") or ""))

    def get_projects(
        self, ids: Iterable[str], *, project_type: ProjectType = "mod"
    ) -> dict[str, Project]:
        """Look up several projects by id, in as few requests as possible.

        Args:
            ids: The projects' numeric ids.
            project_type: The kind to report when CurseForge does not say.

        Returns:
            Each project CurseForge knows, keyed by id. Unknown ids and slugs
            are left out.

        Raises:
            NetworkError: CurseForge could not be reached.
        """
        numbers = sorted({int(item) for item in ids if str(item).isdigit()})
        mods = self._mods(numbers)
        return {
            str(number): mods[number].to_project(self.name, project_type)
            for number in numbers
            if number in mods
        }

    def get_project(
        self, ref: str | int, *, project_type: ProjectType = "modpack"
    ) -> Project:
        """Look up a project by id, slug or URL.

        Args:
            ref: The project's id, slug or web address.
            project_type: The kind of project to look for first. A slug that
                belongs to another kind is still found.

        Returns:
            The project. Its type is the one CurseForge reports, when known.

        Raises:
            PlatformError: No project has that slug.
            NetworkError: CurseForge could not be reached or does not know the id.
        """
        text = project_ref(ref)
        if text.isdigit():
            mod = _Mod.model_validate(self._get(f"/v1/mods/{text}")["data"])
            return mod.to_project(self.name, project_type)
        data = self._search(project_type, slug=text, pageSize=1)
        if not data["data"]:
            # A slug may belong to another kind of project than the one asked for.
            data = self._get("/v1/mods/search", gameId=GAME_ID, slug=text, pageSize=1)
        if not data["data"]:
            raise PlatformError(f"No CurseForge project found for {ref}")
        return _Mod.model_validate(data["data"][0]).to_project(self.name, project_type)

    def iter_releases(
        self,
        project: Project,
        *,
        game_version: str | None = None,
        loader: str | None = None,
        release_only: bool = False,
    ) -> Iterator[Release]:
        """Yield a project's releases, newest first, reading pages as needed.

        Server packs are left out. CurseForge serves at most 10,000 files per
        project, so older releases of a larger project are not listed.

        Args:
            project: The project.
            game_version: Only list this Minecraft version.
            loader: Only list this mod loader.
            release_only: Leave out alpha and beta releases.

        Yields:
            Each release, once.

        Raises:
            NetworkError: CurseForge could not be reached.
        """
        seen: set[int] = set()
        index = 0
        while index + PAGE_SIZE <= MAX_RESULTS:
            data = self._get(
                f"/v1/mods/{project.id}/files",
                gameVersion=game_version,
                modLoaderType=LOADER_TYPES.get(loader or ""),
                index=index,
                pageSize=PAGE_SIZE,
            )
            page = [_File.model_validate(item) for item in data["data"]]
            index += len(page)
            for file in page:
                unwanted = release_only and file.release_type != 1
                if file.id not in seen and not file.is_server_pack and not unwanted:
                    seen.add(file.id)
                    yield file.to_release(self.name)
            pagination: dict[str, Any] = data.get("pagination") or {}
            if not page or index >= pagination.get("totalCount", 0):
                return

    def get_release(self, release_id: str) -> Release:
        """Look up a release by id.

        Args:
            release_id: The file's id.

        Returns:
            The release.

        Raises:
            PlatformError: CurseForge does not know the id.
            NetworkError: CurseForge could not be reached.
        """
        file = self._files([int(release_id)]).get(int(release_id))
        if file is None:
            raise PlatformError(f"No CurseForge file has the id {release_id}")
        return file.to_release(self.name)

    def identify(
        self,
        paths: Iterable[Path | str],
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelToken | None = None,
    ) -> dict[Path, Release]:
        """Find the releases that files came from, by their fingerprints.

        Args:
            paths: The files.
            progress: Receives an update as each file is read.
            cancel: Stops reading files.

        Returns:
            The release of each file CurseForge knows. Other files are left out.

        Raises:
            OSError: A file could not be read.
            NetworkError: CurseForge could not be reached.
            Cancelled: ``cancel`` was triggered.
        """
        groups = digest_files(paths, fingerprint, progress, cancel)
        values = sorted(groups)
        releases: dict[Path, Release] = {}
        for start in range(0, len(values), BATCH_SIZE):
            payload = {"fingerprints": values[start : start + BATCH_SIZE]}
            data = self._post(f"/v1/fingerprints/{GAME_ID}", payload)
            for match in data["data"]["exactMatches"]:
                file = _File.model_validate(match["file"])
                if file.file_fingerprint in groups:
                    release = file.to_release(self.name)
                    releases.update(
                        dict.fromkeys(groups[file.file_fingerprint], release)
                    )
        return releases

    def _files(self, file_ids: list[int]) -> dict[int, _File]:
        """Fetch files by id, in batches."""
        files: dict[int, _File] = {}
        for start in range(0, len(file_ids), BATCH_SIZE):
            batch = file_ids[start : start + BATCH_SIZE]
            try:
                data = self._post("/v1/mods/files", {"fileIds": batch})
            except NetworkError as e:
                # CurseForge answers 404 when none of the ids exist.
                if e.status == 404:
                    continue
                raise
            for item in data["data"]:
                file = _File.model_validate(item)
                files[file.id] = file
        return files

    def _mods(self, mod_ids: list[int]) -> dict[int, _Mod]:
        """Fetch mods by id, in batches."""
        mods: dict[int, _Mod] = {}
        for start in range(0, len(mod_ids), BATCH_SIZE):
            batch = mod_ids[start : start + BATCH_SIZE]
            data = self._post("/v1/mods", {"modIds": batch, "filterPcOnly": False})
            for item in data["data"]:
                mod = _Mod.model_validate(item)
                mods[mod.id] = mod
        return mods

    def _resolved_entry(
        self, entry: PackEntry, file: _File, mod: _Mod | None
    ) -> PackEntry:
        """Fill in an entry from its file and mod."""
        # CurseForge can omit the flag, and only an explicit False forbids downloads.
        allowed = mod is None or mod.allow_mod_distribution is not False
        url = file.download_url if allowed else None
        manual_url = None
        if url is None:
            website = mod.links.website_url if mod and mod.links else None
            base = website or f"https://www.curseforge.com/projects/{file.mod_id}"
            manual_url = f"{base.rstrip('/')}/files/{file.id}"
        folder = CLASS_FOLDERS.get(mod.class_id or 6 if mod else 6, "mods")
        return dataclasses.replace(
            entry,
            path=f"{folder}/{file.file_name}",
            urls=(url,) if url else (),
            hashes=file.hash_map,
            size=file.file_length,
            manual_url=manual_url,
        )

    def resolve(self, pack: Modpack) -> Modpack:
        """Look up download details for a CurseForge pack.

        A file whose author disallows third-party downloads stays unresolved and
        carries a ``manual_url``. A file CurseForge no longer lists also stays
        unresolved, with no ``manual_url``.

        Args:
            pack: The modpack.

        Returns:
            The modpack with resolved entries.

        Raises:
            NetworkError: CurseForge could not be reached.
        """
        pending = [
            entry
            for entry in pack.entries
            if entry.ref and entry.ref.platform == self.name and not entry.is_resolved
        ]
        ids = [int(entry.ref.file_id) for entry in pending if entry.ref]
        files = self._files(ids)
        mods = self._mods(sorted({file.mod_id for file in files.values()}))

        def resolved(entry: PackEntry) -> PackEntry:
            if entry.ref is None or entry.ref.platform != self.name:
                return entry
            file = files.get(int(entry.ref.file_id))
            if file is None:
                return entry
            return self._resolved_entry(entry, file, mods.get(file.mod_id))

        return pack.with_entries(tuple(resolved(entry) for entry in pack.entries))
