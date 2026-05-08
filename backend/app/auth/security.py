from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

import jwt

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.ids import new_id


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_secret(value: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return sha256(f"{settings.jwt_secret_key}:{value}".encode()).hexdigest()


def create_refresh_token() -> str:
    return f"rt_{token_urlsafe(32)}"


def create_access_token(user_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": new_id("jwt"),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AppError("AUTH_EXPIRED_TOKEN", "登录状态已过期", status_code=401) from exc
    except jwt.PyJWTError as exc:
        raise AppError("AUTH_INVALID_TOKEN", "登录状态无效", status_code=401) from exc

    if payload.get("typ") != "access" or not payload.get("sub"):
        raise AppError("AUTH_INVALID_TOKEN", "登录状态无效", status_code=401)
    return payload


def access_token_expires_in_seconds(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    return settings.jwt_access_token_expire_minutes * 60
