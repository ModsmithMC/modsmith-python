import errno
import os

import pytest

from modsmith import _support
from modsmith._support import replace_file, write_atomic


def test_replace_file_falls_back_when_rename_is_refused(tmp_path, monkeypatch):
    def refuse(source, dest):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(_support.os, "replace", refuse)
    source = tmp_path / "a.part"
    dest = tmp_path / "a"
    source.write_bytes(b"new")
    dest.write_bytes(b"old")
    replace_file(source, dest)
    assert dest.read_bytes() == b"new"
    assert not source.exists()


def test_replace_file_does_not_hide_other_errors(tmp_path, monkeypatch):
    def refuse(source, dest):
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(_support.os, "replace", refuse)
    source = tmp_path / "a.part"
    source.write_bytes(b"new")
    with pytest.raises(PermissionError):
        replace_file(source, tmp_path / "a")
    assert source.exists()


def test_write_atomic_creates_parents(tmp_path):
    path = tmp_path / "a" / "b" / "c.txt"
    write_atomic(path, b"x")
    assert path.read_bytes() == b"x"
    assert os.listdir(path.parent) == ["c.txt"]
