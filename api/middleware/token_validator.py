import jwt
import os
from typing import Any

from fastapi import  HTTPException, Header

def _get_jwt_secret() -> str:
    """Get JWT secret from environment or use default (NOT SECURE for production)."""
    return os.getenv("JWT_SECRET", "change-me")

async def validate_token(authorization: str | None = Header(None)) -> dict[str, Any]:
    """Dependency to validate JWT token from Authorization header.
    
    Expected header format: Authorization: Bearer <token>
    
    Returns:
        dict with token claims (sub=username, user_id, exp)
    
    Raises:
        HTTPException 401 if token is missing, invalid, or expired
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization header format. Expected: Bearer <token>")
    
    try:
        secret = _get_jwt_secret()
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
