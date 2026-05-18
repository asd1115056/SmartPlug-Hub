"""Bearer token authentication for the admin API."""

from fastapi import Header, HTTPException

from ..core.settings import get_admin_token


async def require_admin(authorization: str = Header(default="")) -> None:
    token = get_admin_token()
    if not token or authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")
