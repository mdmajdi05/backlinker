"""FastAPI dependencies (authentication, authorisation, pagination)."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_local_token: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the authenticated user.

    Supports two mechanisms:
      * JWT bearer tokens (web + desktop clients talking to a remote backend)
      * a local shared token used by the bundled desktop backend over loopback
    """
    if x_local_token and settings.secret_key and _same_token(x_local_token):
        user = db.execute(select(User).order_by(User.created_at).limit(1)).scalar_one_or_none()
        if user is None:
            # The local token belongs to this machine.  Create the local
            # account on first use so the desktop app works without a sign in
            # and without a race between the window and the first request.
            from app.core.security import hash_password

            user = User(
                email="local@autobacklinker.invalid",
                password_hash=hash_password(secrets.token_urlsafe(32)),
                name="Local user",
                is_active=True,
                is_admin=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "not_authenticated", "message": "Authentication required"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Invalid or expired token"},
        )
    user_id = payload.get("sub")
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_user", "message": "User is not active"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "Administrator privileges required"},
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def _local_token() -> str:
    from app.core.config import settings as s

    return getattr(s, "local_token", "") or ""


def _same_token(candidate: str) -> bool:
    """Constant time comparison of the local token."""
    import hmac

    expected = _local_token()
    if not expected:
        return False
    return hmac.compare_digest(candidate, expected)


class PaginationParams:
    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=500),
        sort: str | None = Query(default=None),
        order: str = Query(default="desc", pattern="^(asc|desc)$"),
    ):
        self.page = page
        self.page_size = page_size
        self.sort = sort
        self.order = order


Pagination = Annotated[PaginationParams, Depends(PaginationParams)]
