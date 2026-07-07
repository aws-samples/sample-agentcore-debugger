"""
Settings API — runtime-configurable application settings.

Lets an admin choose the Bedrock model used for code analysis/fixes from the
Settings UI, with no code edits or redeploys.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Dict, Any
import logging

from app.core.security import get_current_user, require_role, Role
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])

settings_service = SettingsService()


class SetModelRequest(BaseModel):
    model_id: str


@router.get("/model", dependencies=[Depends(get_current_user)])
async def get_model_settings() -> Dict[str, Any]:
    """Get the active model and the list of available models."""
    return settings_service.get_model_settings()


@router.put("/model", dependencies=[Depends(require_role(Role.ADMIN))])
async def set_model(request: SetModelRequest) -> Dict[str, Any]:
    """Set the active model for code analysis/fixes (admin only)."""
    return settings_service.set_model(request.model_id)
