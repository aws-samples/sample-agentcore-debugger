"""
Error analysis API endpoints
"""
from fastapi import APIRouter, Query, HTTPException, Depends
from app.core.security import get_current_user, require_role, Role, CurrentUser
from typing import Optional, List
from datetime import datetime

from app.services.error_service import ErrorService
from app.models.error import (
    LogEvent, ErrorAnalysis, TraceAnalysis, ErrorPattern
)

router = APIRouter(
    prefix="/errors",
    tags=["errors"],
    dependencies=[Depends(get_current_user)],  # All endpoints require authentication
)

# Initialize service
error_service = ErrorService()


@router.get("/logs", response_model=List[LogEvent])
async def get_error_logs(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    log_group: Optional[str] = Query(None, description="Filter by log group"),
    start_time: Optional[datetime] = Query(None, description="Start time for log search"),
    end_time: Optional[datetime] = Query(None, description="End time for log search"),
    error_type: Optional[str] = Query(None, description="Filter by error type"),
    severity: Optional[str] = Query(None, description="Filter by severity (ERROR, WARN, etc.)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs to return")
):
    """
    Get error logs with optional filters.
    
    Returns parsed log events from CloudWatch with error/warning information.
    """
    try:
        logs = await error_service.get_error_logs(
            agent_id=agent_id,
            log_group=log_group,
            start_time=start_time,
            end_time=end_time,
            error_type=error_type,
            severity=severity,
            limit=limit
        )
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyze", response_model=ErrorAnalysis)
async def analyze_errors(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    start_time: Optional[datetime] = Query(None, description="Start time for analysis"),
    end_time: Optional[datetime] = Query(None, description="End time for analysis")
):
    """
    Analyze errors and return summary statistics.
    
    Provides error counts by type, severity, affected agents, and recent errors.
    """
    try:
        analysis = await error_service.analyze_errors(
            agent_id=agent_id,
            start_time=start_time,
            end_time=end_time
        )
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces", response_model=TraceAnalysis)
async def get_trace_errors(
    start_time: Optional[datetime] = Query(None, description="Start time for trace search"),
    end_time: Optional[datetime] = Query(None, description="End time for trace search"),
    filter_expression: Optional[str] = Query(None, description="X-Ray filter expression")
):
    """
    Get X-Ray trace errors and performance analysis.
    
    Returns trace spans with errors/faults and performance metrics.
    """
    try:
        analysis = await error_service.get_trace_errors(
            start_time=start_time,
            end_time=end_time,
            filter_expression=filter_expression
        )
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/patterns", response_model=List[ErrorPattern])
async def detect_error_patterns(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    start_time: Optional[datetime] = Query(None, description="Start time for pattern detection"),
    end_time: Optional[datetime] = Query(None, description="End time for pattern detection")
):
    """
    Detect recurring error patterns.
    
    Analyzes logs to find common error patterns with suggested fixes.
    """
    try:
        patterns = await error_service.detect_error_patterns(
            agent_id=agent_id,
            start_time=start_time,
            end_time=end_time
        )
        return patterns
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/types")
async def get_error_types():
    """
    Get list of known error types with descriptions.
    """
    return {
        "error_types": [
            {"type": "timeout", "description": "Request or operation timeout"},
            {"type": "authentication", "description": "Authentication or authorization failure"},
            {"type": "rate_limit", "description": "Rate limiting or throttling"},
            {"type": "validation", "description": "Input validation error"},
            {"type": "service_error", "description": "Internal service error"},
            {"type": "network", "description": "Network connectivity issue"},
            {"type": "permission", "description": "Permission denied"},
            {"type": "resource_not_found", "description": "Resource not found"},
            {"type": "configuration", "description": "Configuration error"},
            {"type": "dependency", "description": "External dependency failure"},
            {"type": "memory", "description": "Memory-related error"},
            {"type": "database", "description": "Database error"},
            {"type": "generic_error", "description": "Generic error"},
            {"type": "unknown", "description": "Unknown error type"}
        ]
    }
