"""Install or update a Modrinth modpack for the official launcher.

    uv run python examples/install_modpack.py fabulously-optimized 1.21.1

This shows how the modules compose. Modsmith has no pipeline of its own: every
step below is a public call you can replace, reorder or extend.
"""

import sys
from pathlib import Path

import modsmith as ms


def show(event: ms.Progress) -> None:
    total = f"/{event.total}" if event.total else ""
    print(f"\r{event.task}: {event.current}{total} {event.unit}".ljust(60), end="")


def main(slug: str, game_version: str) -> None:
    game = ms.minecraft.GameDir.default()
    launcher = ms.launcher.Launcher(game)
    if ms.launcher.is_running():
        raise SystemExit("Close the Minecraft launcher first")

    with ms.platforms.Modrinth("modsmith-example/1.0") as modrinth:
        project = modrinth.get_project(slug)
        releases = modrinth.list_releases(
            project, game_version=game_version, release_only=True
        )
        cache = Path(".cache")
        pack = modrinth.resolve(
            ms.packs.load(modrinth.fetch(releases[0], cache, progress=show))
        )

        version_id = pack.loader.install(game, session=modrinth.session, progress=show)

        instance = ms.instances.Instance.open(game.path / "modsmith" / project.slug)
        changes = instance.sync(pack, session=modrinth.session, progress=show)

    launcher.add_profile(pack.name, version_id, instance.path, memory_mb=4096)
    print(f"\nInstalled {pack.name} {pack.version} into {instance.path}")
    print(f"{len(changes.added)} added, {len(changes.updated)} updated")
    if changes.conflicts:
        print(f"Kept your changes to: {', '.join(changes.conflicts)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
