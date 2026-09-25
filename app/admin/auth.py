"""Admin API authentication — Bearer token."""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core import tokens_match

_scheme = HTTPBearer()


def require_admin(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_scheme),
) -> None:
    if not tokens_match(creds.credentials, request.app.state.admin_token):
        raise HTTPException(status_code=401, detail="Invalid token")
