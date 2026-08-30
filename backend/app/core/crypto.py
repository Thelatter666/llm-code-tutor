import os
from pathlib import Path

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    key = os.environ.get("APP_SECRET")
    if not key:
        path = Path(get_settings().app_secret_path)
        if not path.exists():
            key = Fernet.generate_key().decode()
            path.write_text(key)
        else:
            key = path.read_text().strip()
    return Fernet(key.encode())


def encrypt_api_key(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_api_key(cipher: str) -> str:
    return _fernet().decrypt(cipher.encode()).decode()


def mask_api_key(plain: str | None) -> str:
    if not plain:
        return ""
    return f"{plain[:3]}****{plain[-4:]}"
