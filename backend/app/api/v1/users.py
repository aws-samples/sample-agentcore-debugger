"""
User Management API endpoints (admin only)

Allows admins to create users, assign roles, and manage access
via Cognito User Pool — no AWS console needed.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
import logging
import boto3

from app.core.config import settings
from app.core.security import require_role, Role

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_role(Role.ADMIN))],
)


# ── Request models ───────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    email: str
    role: str = "viewer"  # viewer | operator | admin
    temporary_password: Optional[str] = None  # auto-generated if not provided


class UpdateUserRoleRequest(BaseModel):
    email: str
    role: str  # viewer | operator | admin


class DeleteUserRequest(BaseModel):
    email: str


# ── Helpers ──────────────────────────────────────────────────────────

VALID_ROLES = {"viewer", "operator", "admin"}


def _get_cognito_client():
    return boto3.client("cognito-idp", region_name=settings.COGNITO_REGION)


def _get_user_groups(client, username: str) -> List[str]:
    """Get all groups a user belongs to."""
    resp = client.admin_list_groups_for_user(
        UserPoolId=settings.COGNITO_USER_POOL_ID,
        Username=username,
    )
    return [g["GroupName"] for g in resp.get("Groups", [])]


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/create")
async def create_user(request: CreateUserRequest) -> Dict[str, Any]:
    """
    Create a new user and assign them a role.
    User will receive a temporary password and must change it on first login.
    """
    if request.role not in VALID_ROLES:
        raise HTTPException(400, f"Invalid role: {request.role}. Must be one of: {VALID_ROLES}")

    client = _get_cognito_client()

    try:
        # Create user with a temporary password first
        params = {
            "UserPoolId": settings.COGNITO_USER_POOL_ID,
            "Username": request.email,
            "UserAttributes": [
                {"Name": "email", "Value": request.email},
                {"Name": "email_verified", "Value": "true"},
            ],
            "DesiredDeliveryMediums": ["EMAIL"],
        }
        if request.temporary_password:
            params["TemporaryPassword"] = request.temporary_password
        else:
            # Generate a strong random password
            import secrets
            import string
            chars = string.ascii_letters + string.digits + "!@#$%^&*"
            params["TemporaryPassword"] = ''.join(secrets.choice(chars) for _ in range(16))

        client.admin_create_user(**params)

        # Set permanent password so user doesn't have to reset on first login
        permanent_password = request.temporary_password or params["TemporaryPassword"]
        client.admin_set_user_password(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=request.email,
            Password=permanent_password,
            Permanent=True,
        )

        # Assign to role group
        client.admin_add_user_to_group(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=request.email,
            GroupName=request.role,
        )

        return {
            "status": "success",
            "email": request.email,
            "role": request.role,
            "message": f"User created with {request.role} role. They'll receive an email with login details — no password reset needed.",
        }

    except client.exceptions.UsernameExistsException:
        raise HTTPException(409, f"User {request.email} already exists")
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(500, str(e))


@router.put("/role")
async def update_user_role(request: UpdateUserRoleRequest) -> Dict[str, Any]:
    """
    Change a user's role. Removes them from all existing role groups
    and adds them to the new one.
    """
    if request.role not in VALID_ROLES:
        raise HTTPException(400, f"Invalid role: {request.role}. Must be one of: {VALID_ROLES}")

    client = _get_cognito_client()

    try:
        # Remove from all existing role groups
        current_groups = _get_user_groups(client, request.email)
        for group in current_groups:
            if group in VALID_ROLES:
                client.admin_remove_user_from_group(
                    UserPoolId=settings.COGNITO_USER_POOL_ID,
                    Username=request.email,
                    GroupName=group,
                )

        # Add to new role group
        client.admin_add_user_to_group(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=request.email,
            GroupName=request.role,
        )

        return {
            "status": "success",
            "email": request.email,
            "previous_roles": [g for g in current_groups if g in VALID_ROLES],
            "new_role": request.role,
        }

    except client.exceptions.UserNotFoundException:
        raise HTTPException(404, f"User {request.email} not found")
    except Exception as e:
        logger.error(f"Failed to update role: {e}")
        raise HTTPException(500, str(e))


@router.get("/list")
async def list_users() -> Dict[str, Any]:
    """List all users with their roles."""
    client = _get_cognito_client()

    try:
        resp = client.list_users(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Limit=60,
        )

        users = []
        for u in resp.get("Users", []):
            attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
            groups = _get_user_groups(client, u["Username"])
            role = next((g for g in groups if g in VALID_ROLES), "viewer")

            users.append({
                "username": u["Username"],
                "email": attrs.get("email", ""),
                "role": role,
                "status": u.get("UserStatus", ""),
                "enabled": u.get("Enabled", False),
                "created": u.get("UserCreateDate", "").isoformat() if u.get("UserCreateDate") else None,
            })

        return {"users": users, "count": len(users)}

    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(500, str(e))


@router.delete("/delete")
async def delete_user(request: DeleteUserRequest) -> Dict[str, Any]:
    """Delete a user from the system."""
    client = _get_cognito_client()

    try:
        client.admin_delete_user(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=request.email,
        )
        return {"status": "success", "message": f"User {request.email} deleted"}

    except client.exceptions.UserNotFoundException:
        raise HTTPException(404, f"User {request.email} not found")
    except Exception as e:
        logger.error(f"Failed to delete user: {e}")
        raise HTTPException(500, str(e))
