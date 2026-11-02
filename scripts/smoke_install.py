"""Install a mod loader into a throwaway directory against the real servers.

Usage:
    uv run python scripts/smoke_install.py forge-36.2.42 1.16.5 --root D:/tmp/mc
    uv run python scripts/smoke_install.py fabric-0.16.10 1.21.1 --root D:/tmp/mc --no-patch

--no-patch skips the step that runs Forge/NeoForge processor jars.
"""

import argparse
import json
from pathlib import Path

from cursecraft import CurseCraft, Settings
from cursecraft.core.events import Event, Message, Progress, StepFinished, StepStarted
from cursecraft.core.paths import maven_path
from cursecraft.core.steps import run_steps
from cursecraft.loaders import LoaderSpec


def report(event: Event) -> None:
    if isinstance(event, StepStarted):
        print(f"[{event.index}/{event.total}] {event.name}")
    elif isinstance(event, StepFinished):
        print("    done")
    elif isinstance(event, Message):
        print(f"    {event.level}: {event.text}")
    elif isinstance(event, Progress) and event.unit == "step":
        print(f"    step {event.current}/{event.total}")


def missing_libraries(root: Path, version_id: str) -> list[str]:
    path = root / "versions" / version_id / f"{version_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = []
    for library in data.get("libraries", []):
        artifact = (library.get("downloads") or {}).get("artifact") or {}
        relative = artifact.get("path") or maven_path(library["name"])
        if not (root / "libraries" / relative).is_file():
            missing.append(relative)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("loader_id")
    parser.add_argument("mc_version")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--no-patch", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(minecraft_dir=root, cache_dir=root / "cache")
    app = CurseCraft(settings, sources={"none": None})

    spec = LoaderSpec.parse(args.loader_id, args.mc_version)
    app.context.versions.ensure_client(spec.mc_version, report)
    plan = app.installers[spec.kind].prepare(spec, app.context)
    steps = [s for s in plan.steps if not (args.no_patch and s.name.startswith("Patch"))]
    run_steps(steps, report)

    missing = missing_libraries(root, plan.version_id)
    print(f"version: {plan.version_id}")
    print(f"missing libraries: {missing or 'none'}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
