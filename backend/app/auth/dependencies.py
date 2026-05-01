from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.core.database import get_db
from app.core.errors import AppError
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AppError("AUTH_REQUIRED", "请先登录", status_code=401)

    payload = decode_access_token(credentials.credentials)
    user = db.get(User, payload["sub"])
    if not user or user.status != "active":
        raise AppError("AUTH_INVALID_TOKEN", "登录状态无效", status_code=401)
    return user
