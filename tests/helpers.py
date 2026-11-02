import hashlib
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_FIXTURES = sorted((FIXTURES / "install_profiles").glob("*.json"))


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()
