"""FastAPI dependencies for admin-protected routes."""
from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from studio.auth.jwt import decode_token

ADMIN_COOKIE = "studio_admin"


def require_admin(request: Request) -> str:
    """Return the admin username if the cookie is valid, else redirect to /admin/login."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise _redirect_to_login()
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise _redirect_to_login()
    return payload["sub"]


def _redirect_to_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin login required",
        headers={"X-Login-Redirect": "/admin/login"},
    )


def optional_admin(request: Request) -> str | None:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return None
    payload = decode_token(token)
    return payload.get("sub") if payload else None
