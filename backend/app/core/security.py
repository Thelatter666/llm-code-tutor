import bcrypt
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from app.core.errors import ApiError


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def _issue(payload: dict, ttl: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {**payload, "iat": now, "exp": now + ttl},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(user_id: str, role: str) -> str:
    ttl = timedelta(minutes=get_settings().access_token_ttl_minutes)
    return _issue({"sub": user_id, "role": role, "typ": "access"}, ttl)


def create_refresh_token(user_id: str) -> str:
    ttl = timedelta(days=get_settings().refresh_token_ttl_days)
    return _issue({"sub": user_id, "typ": "refresh"}, ttl)


def decode_token(token: str, expect: str | None = None) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise ApiError(4010, "登录凭证无效或已过期") from exc
    if expect is not None and payload.get("typ") != expect:
        raise ApiError(4010, "登录凭证无效或已过期")
    return payload
