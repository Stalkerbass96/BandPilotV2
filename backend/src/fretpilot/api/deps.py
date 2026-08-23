"""FastAPI dependency injection — current user, DB session, BYOK vault."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from fretpilot.ai.crypto import KeyVault, get_key_vault
from fretpilot.api.security import verify_token
from fretpilot.config import get_settings
from fretpilot.db.models import User
from fretpilot.db.session import get_db


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    """Extract and verify the JWT, returning the User ORM object."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[len("Bearer "):]
    try:
        user_id = verify_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


def get_key_vault_dependency() -> KeyVault:
    """FastAPI dependency providing a KeyVault instance."""
    return get_key_vault()


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Require a user whose email is configured as a global administrator."""
    if user.email.lower() not in get_settings().admin_email_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return user


__all__ = ["get_current_admin", "get_current_user", "get_key_vault_dependency"]
