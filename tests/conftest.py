import pytest

import modsmith as ms


@pytest.fixture
def session():
    with ms.net.Session(backoff=0) as client:
        yield client
