import threading

import pytest

import modsmith as ms
from modsmith._locks import file_lock
from modsmith.errors import Cancelled, LockedError
from tests.lib.locks import held_elsewhere


def test_lock_creates_its_folder(tmp_path):
    with file_lock(tmp_path / "a" / "b" / "lock"):
        assert (tmp_path / "a" / "b").is_dir()


def test_held_lock_fails_at_once_without_a_wait(tmp_path):
    path = tmp_path / "lock"
    with held_elsewhere(path), pytest.raises(LockedError), file_lock(path, wait=0):
        pytest.fail("the lock should be held")


def test_wait_ends_when_the_holder_leaves(tmp_path):
    path = tmp_path / "lock"
    with held_elsewhere(path) as holder:
        holder.release_later(0.2)
        with file_lock(path, wait=30):
            pass


def test_wait_gives_up(tmp_path):
    path = tmp_path / "lock"
    with held_elsewhere(path), pytest.raises(LockedError), file_lock(path, wait=0.2):
        pytest.fail("the lock should be held")


def test_cancel_stops_the_wait(tmp_path):
    path = tmp_path / "lock"
    token = ms.CancelToken()
    threading.Timer(0.2, token.cancel).start()
    with (
        held_elsewhere(path),
        pytest.raises(Cancelled),
        file_lock(path, wait=30, cancel=token),
    ):
        pytest.fail("the lock should be held")


def test_lock_is_released_when_the_holder_dies(tmp_path):
    path = tmp_path / "lock"
    with held_elsewhere(path) as holder:
        holder.process.kill()
        holder.process.wait()
        with file_lock(path, wait=5):
            pass


def test_same_thread_can_take_a_lock_twice(tmp_path):
    path = tmp_path / "lock"
    with file_lock(path), file_lock(path, wait=0):
        pass
    with held_elsewhere(path):
        pass


def test_lock_keeps_other_threads_out(tmp_path):
    path = tmp_path / "lock"
    failures: list[BaseException] = []

    def attempt() -> None:
        try:
            with file_lock(path, wait=0):
                pass
        except LockedError as e:
            failures.append(e)

    with file_lock(path):
        thread = threading.Thread(target=attempt)
        thread.start()
        thread.join()
    assert len(failures) == 1
