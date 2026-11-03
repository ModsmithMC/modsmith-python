import pytest

from modsmith.platforms._fingerprint import (
    CHUNK_SIZE,
    MASK,
    MULTIPLIER,
    SEED,
    fingerprint,
)


def reference(data: bytes) -> int:
    """MurmurHash2 written byte by byte, as CurseForge's description gives it."""
    data = bytes(byte for byte in data if byte not in (9, 10, 13, 32))
    value = (SEED ^ len(data)) & MASK
    position = 0
    while len(data) - position >= 4:
        word = int.from_bytes(data[position : position + 4], "little")
        word = (word * MULTIPLIER) & MASK
        word ^= word >> 24
        word = (word * MULTIPLIER) & MASK
        value = ((value * MULTIPLIER) & MASK) ^ word
        position += 4
    rest = len(data) - position
    if rest == 3:
        value ^= data[position + 2] << 16
    if rest >= 2:
        value ^= data[position + 1] << 8
    if rest >= 1:
        value ^= data[position]
        value = (value * MULTIPLIER) & MASK
    value ^= value >> 13
    value = (value * MULTIPLIER) & MASK
    return value ^ (value >> 15)


def of(tmp_path, data):
    path = tmp_path / "file.jar"
    path.write_bytes(data)
    return fingerprint(path)


def test_empty_file(tmp_path):
    value = (1 * MULTIPLIER) & MASK
    assert of(tmp_path, b"") == value ^ (value >> 15)


@pytest.mark.parametrize("size", range(9))
def test_matches_the_reference_at_every_tail_length(tmp_path, size):
    data = bytes(range(100, 100 + size))
    assert of(tmp_path, data) == reference(data)


def test_whitespace_is_ignored(tmp_path):
    assert of(tmp_path, b"a b\tc\nd\re") == of(tmp_path, b"abcde")


def test_other_bytes_matter(tmp_path):
    assert of(tmp_path, b"abcde") != of(tmp_path, b"abcdf")


def test_chunk_boundaries_do_not_change_the_result(tmp_path):
    data = (bytes(range(256)) * 4096 * 3)[: CHUNK_SIZE * 2 + 3]
    assert of(tmp_path, data) == reference(data)
