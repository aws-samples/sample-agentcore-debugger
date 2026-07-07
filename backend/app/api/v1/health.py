"""
System Health API endpoints
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any

from app.services.health_service import HealthService
from app.core.security import get_current_user

router = APIRouter(
    prefix="/health",
    tags=["health"],
    dependencies=[Depends(get_current_user)],
)

health_service = HealthService()


@router.get("/system")
async def get_system_health() -> Dict[str, Any]:
    """
    Get overall system health status.
    
    Returns health score, error metrics, and status.
    """
    return await health_service.get_system_health()


@router.get("/agents")
async def get_agent_health_summary() -> Dict[str, Any]:
    """
    Get health summary for all agents.
    
    Returns counts of active, failed, and pending agents.
    """
    return await health_service.get_agent_health_summary()


@router.get("/services")
async def get_service_status() -> List[Dict[str, Any]]:
    """
    Get status of dependent AWS services.
    
    Checks CloudWatch, Bedrock, ECR, and AgentCore.
    """
    return await health_service.get_service_status()


@router.get("/activity")
async def get_recent_activity(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent system activity.
    
    Returns the most recent log events across all agents.
    """
    return await health_service.get_recent_activity(limit=limit)
