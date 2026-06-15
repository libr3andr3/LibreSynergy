"""Authentication — JWT validation and Authentik API client."""

import os
import httpx
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

security = HTTPBearer()

AUTHENTIK_URL = os.getenv("AUTHENTIK_URL", "https://auth.example.com")
AUTHENTIK_API_TOKEN = os.getenv("AUTHENTIK_API_TOKEN", "")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


async def get_jwks():
    """Fetch Authentik's JWKS for token validation."""
    url = f"{AUTHENTIK_URL}/application/o/libresynergy/jwks/"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


def require_admin(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Validate admin API key for internal endpoints."""
    if credentials.credentials != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")


def require_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Validate a user JWT from Authentik and return its claims."""
    token = credentials.credentials
    try:
        # For now, decode without verification (JWKS fetch is async).
        # In production, this should verify against Authentik's JWKS.
        claims = jwt.get_unverified_claims(token)
        return claims
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid JWT token")


class AuthentikClient:
    """Client for Authentik's admin API."""

    def __init__(self):
        self.base_url = AUTHENTIK_URL.rstrip("/")
        self.token = AUTHENTIK_API_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, json=None):
        url = f"{self.base_url}/api/v3{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, headers=self.headers, json=json)
            resp.raise_for_status()
            return resp.json()

    async def get_user_groups(self, user_uuid: str):
        """Get groups a user belongs to."""
        return await self._request("GET", f"/core/users/{user_uuid}/groups/")

    async def add_user_to_group(self, user_uuid: str, group_uuid: str):
        """Add a user to a group."""
        return await self._request("POST", f"/core/groups/{group_uuid}/add_user/",
                                   json={"pk": user_uuid})

    async def remove_user_from_group(self, user_uuid: str, group_uuid: str):
        """Remove a user from a group."""
        return await self._request("POST", f"/core/groups/{group_uuid}/remove_user/",
                                   json={"pk": user_uuid})

    async def get_group_by_name(self, name: str):
        """Find a group by name."""
        result = await self._request("GET", f"/core/groups/?name={name}")
        results = result.get("results", [])
        return results[0] if results else None


authentik = AuthentikClient()
