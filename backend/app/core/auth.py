"""Shared admin-auth dependency.

Header-based admin auth (``X-Admin-Key``) gated on the server's
``ADMIN_API_KEY`` setting. If the env var is unset the dependency is a
no-op (development mode); in production it returns 401 when the
caller-supplied key does not match.
"""

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Raises 401 unless the configured admin key matches the header."""
    if not settings.admin_api_key:
        return
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin key required",
        )
