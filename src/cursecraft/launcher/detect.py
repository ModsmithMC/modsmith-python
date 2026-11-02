import subprocess
import sys

LAUNCHER_PROCESSES = {
    "minecraft.exe",
    "minecraftlauncher.exe",
    "minecraft launcher",
    "minecraft-launcher",
}


def process_names() -> set[str]:
    if sys.platform == "win32":
        command = ["tasklist", "/FO", "CSV", "/NH"]
    else:
        command = ["ps", "-A", "-o", "comm="]
    try:
        output = subprocess.run(
            command, capture_output=True, text=True, errors="replace", timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    if sys.platform == "win32":
        return {
            line.split('","')[0].strip('"').lower() for line in output.splitlines() if line
        }
    return {line.rsplit("/", 1)[-1].strip().lower() for line in output.splitlines()}


def is_launcher_running() -> bool:
    return bool(process_names() & LAUNCHER_PROCESSES)
