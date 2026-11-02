import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import pytest_socket

import modsmith as ms
from tests.lib.builders import build_processor_jars
from tests.lib.server import LocalServer


@pytest.fixture(autouse=True)
def _block_internet(request: pytest.FixtureRequest) -> None:
    """Only tests under tests/live may leave this machine."""
    if "live" not in request.path.parts:
        pytest_socket.socket_allow_hosts(["127.0.0.1"])


@pytest.fixture
def server() -> Iterator[LocalServer]:
    local = LocalServer()
    yield local
    local.close()


@pytest.fixture
def session() -> Iterator[ms.net.Session]:
    with ms.net.Session(backoff=0) as client:
        yield client


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ms.minecraft.GameDir:
    """A game directory that cannot see runtimes installed on this machine."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "no-program-files"))
    return ms.minecraft.GameDir(tmp_path / "minecraft")


def _jdk_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} is not installed")
    return path


@pytest.fixture(scope="session")
def java() -> str:
    return _jdk_tool("java")


@pytest.fixture(scope="session")
def processor_jars(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    return build_processor_jars(tmp_path_factory.mktemp("jars"), _jdk_tool("javac"))
