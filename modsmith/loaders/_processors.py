"""Run the processors of a Forge or NeoForge installer."""

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
    """Return whether this system's zlib is zlib-ng.

    Its compressed output can differ from stock zlib, so a valid patched jar may
    not match its published hash.
    """
    return "ng" in zlib.ZLIB_RUNTIME_VERSION.lower()


def main_class(jar: Path) -> str:
    """Read a jar's ``Main-Class``.

    Raises:
        ProcessorError: The jar or its manifest cannot be read, or has no main class.
    """
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
    """Return a processor's output files and their expected SHA-1."""
    return {
        Path(variables.resolve(key)): variables.resolve(value).lower()
        for key, value in processor.outputs.items()
    }


def outputs_valid(outputs: dict[Path, str]) -> bool:
    """Return whether every output already exists with the right hash.

    Files with the wrong hash are deleted so the processor can rebuild them. With
    no declared outputs this is False, because nothing can prove the work is done.
    """
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
    """Return whether a file is a zip archive with intact contents."""
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except zipfile.BadZipFile:
        return False


def verify_outputs(outputs: dict[Path, str], tolerant: bool) -> None:
    """Check the files a processor produced.

    Args:
        outputs: Expected SHA-1 digests keyed by output file.
        tolerant: Accept a valid jar with a different hash.

    Raises:
        ProcessorError: A file is missing or wrong. A wrong file is deleted.
    """
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
    """Build the command line that runs a processor.

    Args:
        processor: The processor.
        variables: The install's variables.
        java: The Java binary.
        libraries_dir: The game's libraries directory.

    Returns:
        The command and its arguments.

    Raises:
        ProcessorError: The jar or a dependency is missing.
    """
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


def execute(
    command: list[str], cwd: str, cancel: CancelToken | None
) -> tuple[int, str]:
    """Run a command and wait for it, stopping it if ``cancel`` is triggered.

    Args:
        command: The command and its arguments.
        cwd: The working directory.
        cancel: Terminates the process.

    Returns:
        The exit code and the combined output.

    Raises:
        ProcessorError: The command could not be started.
        Cancelled: ``cancel`` was triggered.
    """
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
    """Run processors in order, skipping those whose outputs are already valid.

    Each one runs with a temporary working directory.

    Args:
        processors: The processors.
        variables: The install's variables.
        java: The Java binary.
        libraries_dir: The game's libraries directory.
        progress: Receives one update for each step.
        cancel: Stops the run and terminates the current processor.

    Raises:
        ProcessorError: A processor failed or produced a wrong file.
        Cancelled: ``cancel`` was triggered.
    """
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
