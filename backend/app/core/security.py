"""
Authentication and RBAC security module.

Uses Cognito JWT tokens for authentication and role-based access control.
Roles are derived from Cognito user groups: viewer, operator, admin.

Role hierarchy:
  - viewer:   Can view agents, errors, dashboards
  - operator: viewer + can apply fixes and deploy drafts (test endpoint)
  - admin:    operator + can promote to production, manage settings, manage users
"""
from enum import Enum
from typing import Optional, List
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import boto3
import jwt
import requests
import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Bearer token scheme
bearer_scheme = HTTPBearer(auto_error=False)


class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


# Role hierarchy — higher roles inherit lower role permissions
ROLE_HIERARCHY = {
    Role.VIEWER: [Role.VIEWER],
    Role.OPERATOR: [Role.VIEWER, Role.OPERATOR],
    Role.ADMIN: [Role.VIEWER, Role.OPERATOR, Role.ADMIN],
}


class CurrentUser(BaseModel):
    """Authenticated user context attached to every request."""
    sub: str  # Cognito user ID
    email: str
    username: str
    roles: List[Role]
    token_exp: datetime

    def has_role(self, required: Role) -> bool:
        """Check if user has the required role (respects hierarchy)."""
        for role in self.roles:
            if required in ROLE_HIERARCHY.get(role, []):
                return True
        return False


# ── Cognito JWKS cache ──────────────────────────────────────────────────────

_jwks_cache: Optional[dict] = None
_jwks_cache_time: Optional[float] = None
JWKS_CACHE_TTL = 3600  # 1 hour


def _get_jwks() -> dict:
    """Fetch and cache Cognito JWKS (JSON Web Key Set)."""
    global _jwks_cache, _jwks_cache_time
    import time

    now = time.time()
    if _jwks_cache and _jwks_cache_time and (now - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    if not settings.COGNITO_USER_POOL_ID or not settings.COGNITO_REGION:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cognito is not configured",
        )

    jwks_url = (
        f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/"
        f"{settings.COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )
    try:
        resp = requests.get(jwks_url, timeout=5)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_time = now
        return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        if _jwks_cache:
            return _jwks_cache  # stale is better than nothing
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to fetch Cognito signing keys",
        )


def _find_signing_key(token: str) -> dict:
    """Find the correct RSA public key from JWKS for the given token."""
    jwks = _get_jwks()
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    for key in jwks.get("keys", []):
        if key["kid"] == kid:
            return key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token signing key not found",
    )


# ── Token verification ───────────────────────────────────────────────────────

def _verify_cognito_token(token: str) -> dict:
    """Verify and decode a Cognito JWT token."""
    try:
        signing_key = _find_signing_key(token)

        # Build RSA public key from JWK
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(signing_key))

        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=settings.COGNITO_APP_CLIENT_ID,
            issuer=(
                f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/"
                f"{settings.COGNITO_USER_POOL_ID}"
            ),
            options={"verify_exp": True},
        )
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


# ── Dev mode fallback ────────────────────────────────────────────────────────

def _dev_mode_user() -> CurrentUser:
    """Return a default admin user when auth is disabled (local dev only)."""
    return CurrentUser(
        sub="dev-user-001",
        email="dev@localhost",
        username="dev-user",
        roles=[Role.ADMIN],
        token_exp=datetime.now(timezone.utc) + timedelta(hours=24),
    )


# ── FastAPI dependencies ─────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> CurrentUser:
    """
    Core auth dependency. Extracts and validates the JWT from the
    Authorization header, returning a CurrentUser.

    When AUTH_ENABLED=false (local dev), returns a default admin user.
    """
    if not settings.AUTH_ENABLED:
        return _dev_mode_user()

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _verify_cognito_token(credentials.credentials)

    # Extract roles from Cognito groups
    cognito_groups: List[str] = payload.get("cognito:groups", [])
    roles: List[Role] = []
    for group in cognito_groups:
        group_lower = group.lower()
        if group_lower in [r.value for r in Role]:
            roles.append(Role(group_lower))

    # Default to viewer if no recognized group
    if not roles:
        roles = [Role.VIEWER]

    return CurrentUser(
        sub=payload.get("sub", ""),
        email=payload.get("email", ""),
        username=payload.get("cognito:username", payload.get("sub", "")),
        roles=roles,
        token_exp=datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc),
    )


def require_role(required_role: Role):
    """
    Returns a FastAPI dependency that checks the user has the required role.

    Usage:
        @router.post("/promote", dependencies=[Depends(require_role(Role.ADMIN))])
        async def promote(...):
    """
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role.value}' required. Your roles: {[r.value for r in user.roles]}",
            )
        return user

    return _check
