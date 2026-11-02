import os
import subprocess
import tempfile
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

from ..core.download import file_hash
from ..core.errors import ProcessorError
from ..core.events import Emit, Message, Progress, null_emit
from ..core.paths import maven_path
from .install_profile import Processor, Variables

Runner = Callable[..., subprocess.CompletedProcess]


def uses_zlib_ng() -> bool:
    return "ng" in zlib.ZLIB_RUNTIME_VERSION.lower()


def main_class(jar: Path) -> str:
    try:
        with zipfile.ZipFile(jar) as archive:
            manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8")
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        raise ProcessorError(f"Cannot read manifest of {jar.name}: {e}") from e
    for line in manifest.splitlines():
        if line.startswith("Main-Class:"):
            return line.split(":", 1)[1].strip()
    raise ProcessorError(f"{jar.name} has no Main-Class")


def resolve_outputs(processor: Processor, variables: Variables) -> dict[Path, str]:
    return {
        Path(variables.resolve(key)): variables.resolve(value).lower()
        for key, value in processor.outputs.items()
    }


def outputs_valid(outputs: dict[Path, str]) -> bool:
    if not outputs:
        return False
    valid = True
    for path, expected in outputs.items():
        if not path.is_file():
            valid = False
        elif file_hash(path) != expected:
            path.unlink()
            valid = False
    return valid


def is_valid_jar(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except zipfile.BadZipFile:
        return False


def verify_outputs(outputs: dict[Path, str], tolerant: bool) -> None:
    for path, expected in outputs.items():
        if not path.is_file():
            raise ProcessorError(f"Processor did not produce {path.name}")
        actual = file_hash(path)
        if actual == expected:
            continue
        if tolerant and path.suffix == ".jar" and is_valid_jar(path):
            continue
        path.unlink()
        raise ProcessorError(
            f"Hash mismatch for {path.name}: expected {expected}, got {actual}"
        )


def build_command(
    processor: Processor, variables: Variables, java: Path, libraries_dir: Path
) -> list[str]:
    jar = libraries_dir / maven_path(processor.jar)
    if not jar.is_file():
        raise ProcessorError(f"Missing processor jar: {jar.name}")
    classpath = [jar]
    for coord in processor.classpath:
        path = libraries_dir / maven_path(coord)
        if not path.is_file():
            raise ProcessorError(f"Missing processor dependency: {path.name}")
        classpath.append(path)
    return [
        str(java),
        "-cp",
        os.pathsep.join(map(str, classpath)),
        main_class(jar),
        *[variables.resolve(arg) for arg in processor.args],
    ]


def run_processors(
    processors: list[Processor],
    variables: Variables,
    java: Path,
    libraries_dir: Path,
    emit: Emit = null_emit,
    runner: Runner = subprocess.run,
) -> None:
    tolerant = uses_zlib_ng()
    total = len(processors)
    with tempfile.TemporaryDirectory(prefix="cursecraft-processor-") as work_dir:
        for index, processor in enumerate(processors, start=1):
            emit(Progress("Patching Minecraft", index - 1, total, "step"))
            outputs = resolve_outputs(processor, variables)
            if outputs_valid(outputs):
                continue
            command = build_command(processor, variables, java, libraries_dir)
            try:
                result = runner(
                    command,
                    cwd=work_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as e:
                raise ProcessorError(f"Cannot run {java}: {e}") from e
            if result.returncode != 0:
                tail = "\n".join((result.stdout or "").splitlines()[-20:])
                raise ProcessorError(
                    f"{processor.jar} exited with code {result.returncode}\n{tail}"
                )
            verify_outputs(outputs, tolerant)
    emit(Progress("Patching Minecraft", total, total, "step"))
    emit(Message(f"Ran {total} processor(s) with {java}", "debug"))
