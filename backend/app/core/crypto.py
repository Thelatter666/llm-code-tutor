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
    if len(plain) < 8:
        # L-2：≤7 位时「前 3 + 后 4」会重叠或全量暴露（如 6 位 key → 全文泄露），
        # 短密钥不透露任何片段
        return "****"
    return f"{plain[:3]}****{plain[-4:]}"
