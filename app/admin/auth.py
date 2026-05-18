"""Admin API authentication — Bearer token."""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_scheme = HTTPBearer()


def require_admin(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_scheme),
) -> None:
    if creds.credentials != request.app.state.admin_token:
        raise HTTPException(status_code=401, detail="Invalid token")
