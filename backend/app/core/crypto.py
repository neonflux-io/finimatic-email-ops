from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet


def fingerprint(value: str | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_dotenv_key() -> str | None:
    env_path = _backend_root() / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("FERNET_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def get_fernet_key() -> str:
    key = os.getenv("FERNET_KEY") or _read_dotenv_key()
    if key:
        return key

    generated = Fernet.generate_key().decode("utf-8")
    env_path = _backend_root() / ".env"
    env_path.write_text(f"FERNET_KEY={generated}\n", encoding="utf-8")
    os.environ["FERNET_KEY"] = generated
    return generated


def _fernet() -> Fernet:
    return Fernet(get_fernet_key().encode("utf-8"))


def encrypt_secret(value: str | None) -> str:
    if value is None or value == "":
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def redacted_error(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    for token in ("password", "secret", "token", "key"):
        text = text.replace(token, "<redacted>")
    return text[:300]
