import os
from typing import Optional

from fastapi import Header, HTTPException


def _configured_api_key() -> Optional[str]:
    # Backward-compatible key names.
    return os.getenv("MALODY_API_KEY") or os.getenv("MALODY_API_TOKEN")


def require_api_key(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> bool:
    """
    Guard sensitive endpoints with an optional API key.
    - If no API key is configured, allow access (local/manual deployment).
    - If configured, require either:
      1) X-API-Key: <key>
      2) Authorization: Bearer <key>
    """
    configured = _configured_api_key()
    if not configured:
        return True

    if x_api_key == configured:
        return True

    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token == configured:
            return True

    raise HTTPException(status_code=401, detail="Unauthorized")

