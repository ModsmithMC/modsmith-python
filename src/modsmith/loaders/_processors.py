import logging
import os
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

from ..errors import Cancelled, ProcessorError
from ..minecraft import maven_path
from ..net import file_hash
from ..progress import CancelToken, ProgressCallback, report
from ._install_profile import Processor, Variables

logger = logging.getLogger(__name__)
TASK = "processors"
POLL_SECONDS = 0.2


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
            logger.info("Ignoring hash mismatch for %s under zlib-ng", path.name)
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


def execute(command: list[str], cwd: str, cancel: CancelToken | None) -> tuple[int, str]:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        raise ProcessorError(f"Cannot run {command[0]}: {e}") from e
    while True:
        try:
            output, _ = process.communicate(timeout=POLL_SECONDS)
            return process.returncode, output or ""
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.cancelled:
                process.terminate()
                process.communicate()
                raise Cancelled("Operation cancelled") from None


def run_processors(
    processors: list[Processor],
    variables: Variables,
    java: Path,
    libraries_dir: Path,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> None:
    tolerant = uses_zlib_ng()
    total = len(processors)
    with tempfile.TemporaryDirectory(prefix="modsmith-processor-") as work_dir:
        for index, processor in enumerate(processors):
            if cancel is not None:
                cancel.check()
            report(progress, TASK, index, total, "step")
            outputs = resolve_outputs(processor, variables)
            if outputs_valid(outputs):
                continue
            command = build_command(processor, variables, java, libraries_dir)
            code, output = execute(command, work_dir, cancel)
            if code != 0:
                tail = "\n".join(output.splitlines()[-20:])
                raise ProcessorError(f"{processor.jar} exited with code {code}\n{tail}")
            verify_outputs(outputs, tolerant)
    report(progress, TASK, total, total, "step")
