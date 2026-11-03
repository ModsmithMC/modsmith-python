from dataclasses import dataclass
from typing import ClassVar

import pytest

from modsmith.errors import NetworkError, UnsupportedError
from modsmith.loaders import (
    Fabric,
    Forge,
    Loader,
    LoaderVersion,
    NeoForge,
    Quilt,
    recommended,
    register,
    versions,
)
from tests.lib.server import Reply


def maven(*names: str) -> bytes:
    listed = "".join(f"<version>{name}</version>" for name in names)
    return (
        "<metadata><versioning><versions>"
        + listed
        + "</versions></versioning></metadata>"
    ).encode()


def meta(*entries: tuple[str, bool | None]) -> list[dict]:
    items = []
    for version, stable in entries:
        loader: dict = {"version": version}
        if stable is not None:
            loader["stable"] = stable
        items.append({"loader": loader})
    return items


def summary(found: list[LoaderVersion]) -> list[tuple[str, bool, bool]]:
    return [(item.version, item.stable, item.recommended) for item in found]


def test_fabric_recommends_the_build_it_marks(server, session):
    server.add_json(
        "/fabric/versions/loader/1.21.1",
        meta(("0.17.0-beta.1", False), ("0.16.10", True), ("0.16.9", False)),
    )
    found = Fabric.available("1.21.1", session=session, meta_url=server.url("/fabric"))
    assert summary(found) == [
        ("0.17.0-beta.1", False, False),
        ("0.16.10", True, True),
        ("0.16.9", True, False),
    ]
    assert found[1].loader() == Fabric("0.16.10", "1.21.1")


def test_quilt_has_no_marks_so_the_newest_stable_is_recommended(server, session):
    server.add_json(
        "/quilt/versions/loader/1.21.1",
        meta(("0.31.0-beta.5", None), ("0.30.2", None), ("0.30.10", None)),
    )
    found = Quilt.available("1.21.1", session=session, meta_url=server.url("/quilt"))
    assert summary(found) == [
        ("0.31.0-beta.5", False, False),
        ("0.30.10", True, True),
        ("0.30.2", True, False),
    ]


def test_metadata_services_that_do_not_know_a_version(server, session):
    server.add("/fabric/versions/loader/9.9", Reply(b"unknown", status=400))
    assert (
        Fabric.available("9.9", session=session, meta_url=server.url("/fabric")) == []
    )


def test_forge_uses_its_own_recommendation(server, session):
    server.add_body(
        "/maven/net/minecraftforge/forge/maven-metadata.xml",
        maven("1.20.1-47.1.0", "1.20.1-47.4.28", "1.20-46.0.14", "1.20.1-47.4.30"),
    )
    promotions = server.add_json(
        "/promotions.json", {"promos": {"1.20.1-recommended": "47.4.28"}}
    )
    found = Forge.available(
        "1.20.1",
        session=session,
        repository=server.url("/maven"),
        promotions_url=promotions,
    )
    assert summary(found) == [
        ("47.4.30", True, False),
        ("47.4.28", True, True),
        ("47.1.0", True, False),
    ]


def test_forge_without_a_recommendation_uses_the_newest(server, session):
    server.add_body(
        "/maven/net/minecraftforge/forge/maven-metadata.xml",
        maven("1.21.1-52.0.1", "1.21.1-52.0.10"),
    )
    promotions = server.add_json(
        "/promotions.json", {"promos": {"1.21.1-recommended": "51.0.0"}}
    )
    found = Forge.available(
        "1.21.1",
        session=session,
        repository=server.url("/maven"),
        promotions_url=promotions,
    )
    assert [item.version for item in found if item.recommended] == ["52.0.10"]


def test_neoforge_works_out_the_game_version(server, session):
    server.add_body(
        "/maven/net/neoforged/neoforge/maven-metadata.xml",
        maven(
            "21.1.9",
            "26.3.0.100",
            "21.1.80-beta",
            "21.0.5",
            "21.1.77",
            "20.2.3-beta",
            "26.1.2.125",
            "not-a-version",
        ),
    )
    repository = server.url("/maven")

    def listed(minecraft: str) -> list[tuple[str, bool, bool]]:
        return summary(
            NeoForge.available(minecraft, session=session, repository=repository)
        )

    assert listed("1.21.1") == [
        ("21.1.80-beta", False, False),
        ("21.1.77", True, True),
        ("21.1.9", True, False),
    ]
    assert listed("1.21") == [("21.0.5", True, True)]
    assert listed("1.20.2") == [("20.2.3-beta", False, False)]
    assert listed("26.3") == [("26.3.0.100", True, True)]
    assert listed("26.1.2") == [("26.1.2.125", True, True)]


def test_neoforge_for_minecraft_1_20_1_uses_the_forge_artifact(server, session):
    server.add_body(
        "/maven/net/neoforged/forge/maven-metadata.xml",
        maven("1.20.1-47.1.3", "1.20.1-47.1.106"),
    )
    found = NeoForge.available(
        "1.20.1", session=session, repository=server.url("/maven")
    )
    assert [item.version for item in found] == ["47.1.106", "47.1.3"]
    assert found[0].loader() == NeoForge("47.1.106", "1.20.1")


def test_broken_maven_metadata(server, session):
    server.add_body("/maven/net/neoforged/neoforge/maven-metadata.xml", b"<metadata")
    with pytest.raises(NetworkError, match="Invalid Maven metadata"):
        NeoForge.available("1.21.1", session=session, repository=server.url("/maven"))


@register
@dataclass(frozen=True)
class Listed(Loader):
    """A loader whose versions come from a list in this test."""

    kind: ClassVar[str] = "listed-for-tests"
    published: ClassVar[list[LoaderVersion]] = []

    @classmethod
    def available(cls, minecraft, *, session=None):
        return [item for item in cls.published if item.minecraft == minecraft]

    def version_id(self, *, session=None, cache_dir=None):
        return self.version

    def install(self, game, **options):
        return self.version


@register
@dataclass(frozen=True)
class Unlisted(Loader):
    """A loader that cannot list its versions."""

    kind: ClassVar[str] = "unlisted-for-tests"

    def version_id(self, *, session=None, cache_dir=None):
        return self.version

    def install(self, game, **options):
        return self.version


def test_recommended_picks_the_marked_version():
    kind = Listed.kind
    Listed.published = [
        LoaderVersion(kind, "2-beta", "1.0", stable=False),
        LoaderVersion(kind, "1", "1.0", recommended=True),
    ]
    assert recommended(kind, "1.0") == Listed("1", "1.0")
    assert [item.version for item in versions(kind, "1.0")] == ["2-beta", "1"]


def test_recommended_falls_back_to_the_newest():
    kind = Listed.kind
    Listed.published = [LoaderVersion(kind, "2-beta", "1.0", stable=False)]
    assert recommended(kind, "1.0") == Listed("2-beta", "1.0")


def test_recommended_with_nothing_to_offer():
    Listed.published = []
    with pytest.raises(UnsupportedError, match=r"no version for Minecraft 1.0"):
        recommended(Listed.kind, "1.0")
    with pytest.raises(UnsupportedError, match="cannot list its versions"):
        versions(Unlisted.kind, "1.0")
    with pytest.raises(UnsupportedError, match="Unsupported mod loader"):
        versions("no-such-loader", "1.0")
