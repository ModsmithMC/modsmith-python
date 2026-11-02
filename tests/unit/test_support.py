import os
from pathlib import Path

import pytest

import modsmith as ms
from modsmith._support import copy_replace, replace_file, slugify, write_atomic
from modsmith.errors import Cancelled


def test_write_atomic_creates_parents_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "a" / "b" / "c.txt"
    write_atomic(path, b"x")
    assert path.read_bytes() == b"x"
    assert os.listdir(path.parent) == ["c.txt"]


def test_copy_replace_overwrites_and_removes_source(tmp_path):
    source = tmp_path / "a.part"
    dest = tmp_path / "a"
    source.write_bytes(b"new")
    dest.write_bytes(b"old")
    copy_replace(source, dest)
    assert dest.read_bytes() == b"new"
    assert not source.exists()


def test_replace_file_crosses_real_filesystems(tmp_path):
    other = Path.cwd() / ".pytest_cache" / "cross-device"
    other.mkdir(parents=True, exist_ok=True)
    if os.stat(other).st_dev == os.stat(tmp_path).st_dev:
        pytest.skip("the working directory and temp share a filesystem")
    source = tmp_path / "a.part"
    dest = other / "a"
    source.write_bytes(b"new")
    replace_file(source, dest)
    assert dest.read_bytes() == b"new"
    assert not source.exists()
    dest.unlink()


@pytest.mark.parametrize(
    ("name", "slug"),
    [("All The Mods 10", "all-the-mods-10"), ("整合包", "instance"), ("A--B!", "a-b")],
)
def test_slugify(name, slug):
    assert slugify(name) == slug


def test_cancel_token():
    token = ms.CancelToken()
    token.check()
    token.cancel()
    assert token.cancelled
    with pytest.raises(Cancelled):
        token.check()


def test_every_error_derives_from_base():
    for name in ms.errors.__all__:
        assert issubclass(getattr(ms.errors, name), ms.errors.ModsmithError)
