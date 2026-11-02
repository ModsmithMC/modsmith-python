"""Every test here starts a real JVM running a real processor jar."""

import shutil
import threading
import time
import zipfile
from pathlib import Path

import pytest

import modsmith as ms
from modsmith.errors import Cancelled, ProcessorError
from modsmith.loaders import Processor
from modsmith.loaders._install_profile import Variables
from modsmith.loaders._processors import run_processors, verify_outputs
from modsmith.minecraft import maven_path
from tests.lib.builders import sha1


@pytest.fixture
def libraries(tmp_path, processor_jars):
    root = tmp_path / "libraries"
    for coord, jar in zip(
        ("demo:tool:1", "demo:helper:1"), processor_jars, strict=True
    ):
        dest = root / maven_path(coord)
        dest.parent.mkdir(parents=True)
        shutil.copy(jar, dest)
    return root


def tool(*args, outputs=None, classpath=("demo:helper:1",)):
    return Processor(
        jar="demo:tool:1",
        classpath=list(classpath),
        args=list(args),
        outputs=outputs or {},
    )


def run(processors, libraries, java, tokens=None, **kwargs):
    variables = Variables(libraries, tokens or {})
    run_processors(processors, variables, Path(java), libraries, **kwargs)


def test_runs_a_real_processor_with_its_classpath(tmp_path, libraries, java):
    out = tmp_path / "out.txt"
    events = []
    run(
        [tool("--print", "hello", "--write", "{OUT}", "done")],
        libraries,
        java,
        {"OUT": str(out)},
        progress=events.append,
    )
    assert out.read_text() == "done"
    assert events[-1] == ms.Progress("processors", 1, 1, "step")


def test_resolves_library_arguments(tmp_path, libraries, java):
    out = tmp_path / "copy.jar"
    run(
        [tool("--copy", "[demo:helper:1]", "{OUT}")],
        libraries,
        java,
        {"OUT": str(out)},
    )
    assert out.read_bytes() == (libraries / maven_path("demo:helper:1")).read_bytes()


def test_missing_classpath_entry_fails_in_the_jvm(libraries, java):
    with pytest.raises(ProcessorError, match="NoClassDefFoundError"):
        run([tool("--print", "x", classpath=())], libraries, java)


def test_valid_outputs_skip_the_processor(tmp_path, libraries, java):
    out = tmp_path / "out.txt"
    out.write_text("done")
    processor = tool("--exit", "3", outputs={"{OUT}": f"'{sha1(b'done')}'"})
    run([processor], libraries, java, {"OUT": str(out)})


def test_stale_output_is_rebuilt(tmp_path, libraries, java):
    out = tmp_path / "out.txt"
    out.write_text("stale")
    processor = tool(
        "--write", "{OUT}", "done", outputs={"{OUT}": f"'{sha1(b'done')}'"}
    )
    run([processor], libraries, java, {"OUT": str(out)})
    assert out.read_text() == "done"


def test_failure_stops_the_chain_and_reports_output(tmp_path, libraries, java):
    marker = tmp_path / "marker"
    processors = [tool("--exit", "3"), tool("--write", "{OUT}", "x")]
    with pytest.raises(ProcessorError, match="processed:failing"):
        run(processors, libraries, java, {"OUT": str(marker)})
    assert not marker.exists()


def test_output_hash_mismatch_fails_and_removes_the_file(tmp_path, libraries, java):
    out = tmp_path / "out.txt"
    processor = tool(
        "--write", "{OUT}", "wrong", outputs={"{OUT}": f"'{sha1(b'right')}'"}
    )
    with pytest.raises(ProcessorError, match="Hash mismatch"):
        run([processor], libraries, java, {"OUT": str(out)})
    assert not out.exists()


def test_missing_output_fails(tmp_path, libraries, java):
    out = tmp_path / "never-written"
    processor = tool("--print", "x", outputs={"{OUT}": f"'{sha1(b'x')}'"})
    with pytest.raises(ProcessorError, match="did not produce"):
        run([processor], libraries, java, {"OUT": str(out)})


def test_cancel_terminates_a_running_jvm(libraries, java):
    token = ms.CancelToken()
    threading.Timer(1.0, token.cancel).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run([tool("--sleep", "120000")], libraries, java, cancel=token)
    assert time.monotonic() - started < 30


def test_missing_java_is_reported(tmp_path, libraries):
    with pytest.raises(ProcessorError, match="Cannot run"):
        run([tool("--print", "x")], libraries, tmp_path / "no-java")


def test_missing_processor_jar_is_reported(tmp_path, java):
    with pytest.raises(ProcessorError, match="Missing processor jar"):
        run([tool("--print", "x")], tmp_path, java)


def test_jar_without_main_class_is_reported(libraries, java):
    jar = libraries / maven_path("demo:tool:1")
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    with pytest.raises(ProcessorError, match="no Main-Class"):
        run([tool("--print", "x")], libraries, java)


def test_tolerant_verification_accepts_a_valid_jar(tmp_path):
    jar = tmp_path / "out.jar"
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr("a", "b")
    verify_outputs({jar: "0" * 40}, tolerant=True)
    assert jar.exists()


def test_tolerant_verification_rejects_a_broken_jar(tmp_path):
    jar = tmp_path / "out.jar"
    jar.write_bytes(b"not a zip")
    with pytest.raises(ProcessorError):
        verify_outputs({jar: "0" * 40}, tolerant=True)
