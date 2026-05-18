"""Bearer token authentication for the admin API."""

import os

from fastapi import Header, HTTPException


ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


async def require_admin(authorization: str = Header(default="")) -> None:
    if not ADMIN_TOKEN or authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
