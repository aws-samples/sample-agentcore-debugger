"""
Fix workflow API endpoints
"""
from fastapi import APIRouter, Query, HTTPException, Depends
from app.core.security import get_current_user, require_role, Role, CurrentUser
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import uuid
import json
import os
import re

import boto3
from botocore.config import Config

from app.services.fix_service import FixService
from app.models.fix import (
    ErrorCluster, FixRequest, FixResult, ContinueFixRequest,
    ErrorAnalysisRequest, ErrorAnalysisResult,
    ErrorClustersResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fix", tags=["fix"])

# ── RBAC: read-only endpoints use viewer, mutation endpoints use operator ──

# Thread pool for running blocking operations
_executor = ThreadPoolExecutor(max_workers=4)

# Initialize service
fix_service = FixService()

# Simple cache for error clusters (agent_id -> (timestamp, data))
_clusters_cache: Dict[str, Tuple[float, List[ErrorCluster]]] = {}
CACHE_TTL_SECONDS = 60  # Cache for 1 minute

# ---------------------------------------------------------------------------
# Job status storage (DynamoDB — shared across all gunicorn workers).
#
# Status is keyed by a server-generated job id and persisted in the shared
# state table. Using a key/value store (not the filesystem) means the job id
# is never used to build a filesystem path, so path-traversal is not possible.
# ---------------------------------------------------------------------------
_JOB_PK = "FIXJOB"
_JOB_TTL_SECONDS = 24 * 60 * 60  # auto-expire job records after 24h

# Job IDs are server-generated as "{agent_id}_{pattern_id}_{uuid8}". Validate to
# a safe character set as a basic input-hygiene guard.
_JOB_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,128}$')

_ddb_resource = boto3.resource(
    "dynamodb",
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    config=Config(retries={"mode": "adaptive", "max_attempts": 10}),
)


def _safe_job_id(job_id: str) -> str:
    if not _JOB_ID_RE.match(job_id or ""):
        raise HTTPException(status_code=400, detail="Invalid job id")
    return job_id


def _job_table():
    table_name = os.getenv("DYNAMODB_TABLE_NAME", "")
    if not table_name:
        raise HTTPException(status_code=500, detail="Job store is not configured")
    return _ddb_resource.Table(table_name)


def _save_job_status(job_id: str, status: Dict[str, Any]):
    safe = _safe_job_id(job_id)
    # Store the status payload as a JSON string to avoid DynamoDB float/Decimal
    # type juggling for arbitrarily-nested fix results.
    _job_table().put_item(Item={
        "PK": _JOB_PK,
        "SK": safe,
        "data": json.dumps(status),
        "ttl": int(time.time()) + _JOB_TTL_SECONDS,
    })


def _load_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    safe = _safe_job_id(job_id)
    resp = _job_table().get_item(Key={"PK": _JOB_PK, "SK": safe}, ConsistentRead=True)
    item = resp.get("Item")
    if item and item.get("data"):
        return json.loads(item["data"])
    return None



@router.get("/clusters/{agent_id}", response_model=ErrorClustersResponse,
             dependencies=[Depends(get_current_user)])
async def get_error_clusters(
    agent_id: str,
    start_time: Optional[datetime] = Query(None, description="Start time for error search"),
    end_time: Optional[datetime] = Query(None, description="End time for error search"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of clusters"),
    refresh: bool = Query(False, description="Force refresh cache")
):
    """
    Get clustered error patterns for an agent with suppression summary.
    
    Returns error patterns grouped by type and similarity, ready for fixing.
    Also includes suppression summary showing how many duplicate errors were deduplicated.
    Results are cached for 60 seconds.
    """
    try:
        # Check cache first (unless refresh requested)
        # Include time range in cache key so different ranges get different results
        cache_key = f"{agent_id}_{start_time}_{end_time}"
        now = time.time()
        
        if not refresh and cache_key in _clusters_cache:
            cached_time, cached_data = _clusters_cache[cache_key]
            if now - cached_time < CACHE_TTL_SECONDS:
                return cached_data
        
        # Fetch fresh data with suppression summary
        response = await fix_service.get_error_clusters_with_summary(
            agent_id=agent_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        
        # Update cache
        _clusters_cache[cache_key] = (now, response)
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze", response_model=ErrorAnalysisResult,
             dependencies=[Depends(get_current_user)])
async def analyze_error(request: ErrorAnalysisRequest):
    """
    Analyze an error cluster using AI.
    
    Returns classification, recommendations, and suggested fixes.
    """
    try:
        result = await fix_service.analyze_error(
            agent_id=request.agent_id,
            error_cluster=request.error_cluster
        )
        return ErrorAnalysisResult(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _run_fix_workflow_sync(job_id: str, request: FixRequest):
    """Synchronous background task to run the fix workflow in a thread"""
    try:
        job_status = _load_job_status(job_id) or {}
        job_status['status'] = 'analyzing'
        _save_job_status(job_id, job_status)
        
        logger.info(f"[Job {job_id}] Starting fix workflow for agent {request.agent_id}")
        
        # OPTIMIZATION: Use pre-computed analysis if provided (avoids redundant classification)
        if request.pre_analysis:
            logger.info(f"[Job {job_id}] Using pre-computed analysis (skipping redundant classification)")
            analysis = request.pre_analysis
        else:
            # Fallback: analyze the error if no pre-analysis provided
            logger.info(f"[Job {job_id}] No pre-analysis provided, running analysis...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                analysis = loop.run_until_complete(fix_service.analyze_error(
                    agent_id=request.agent_id,
                    error_cluster=request.error_cluster
                ))
            finally:
                loop.close()
        
        logger.info(f"[Job {job_id}] Analysis complete, starting fix")
        
        job_status['status'] = 'fixing'
        job_status['analysis'] = analysis
        _save_job_status(job_id, job_status)
        
        # Start the fix workflow - run sync version
        # When pre_analysis is provided, it IS the analysis dict directly.
        # When analyze_error() is called, it returns {status, analysis: {...}, ...}
        # so we need analysis.get('analysis', analysis) to handle both cases.
        ai_analysis_for_fixer = analysis.get('analysis', analysis)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(fix_service.start_fix_workflow(
                agent_id=request.agent_id,
                pattern_id=request.pattern_id,
                ai_analysis=ai_analysis_for_fixer,
                user_choice=request.user_choice,
                is_fix_all=request.is_fix_all,
                fix_all_session_id=request.fix_all_session_id
            ))
        finally:
            loop.close()
        
        logger.info(f"[Job {job_id}] Fix workflow completed with status: {result.status if hasattr(result, 'status') else 'unknown'}")
        
        job_status['status'] = 'completed'
        job_status['result'] = result.dict() if hasattr(result, 'dict') else result
        _save_job_status(job_id, job_status)
        
    except Exception as e:
        logger.error(f"Fix workflow failed for job {job_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        job_status = _load_job_status(job_id) or {}
        job_status['status'] = 'failed'
        job_status['error'] = str(e)
        _save_job_status(job_id, job_status)


@router.post("/start",
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def start_fix_workflow_endpoint(request: FixRequest):
    """
    Start the auto-fix workflow for an error pattern (async).
    
    Returns immediately with a job_id. Poll /fix/job/{job_id} for status.
    
    This will:
    1. Classify the error type
    2. Download agent code from ECR (if needed)
    3. Run appropriate agents (Library Agent, Code Agent, or both)
    4. Return fix results or await user choice for mixed workflows
    """
    start_time = time.time()
    try:
        job_id = f"{request.agent_id}_{request.pattern_id}_{uuid.uuid4().hex[:8]}"
        
        logger.info(f"[/fix/start] Creating job {job_id} at {datetime.utcnow().isoformat()}")
        
        job_status = {
            'job_id': job_id,
            'agent_id': request.agent_id,
            'pattern_id': request.pattern_id,
            'status': 'pending',
            'created_at': datetime.utcnow().isoformat(),
            'result': None,
            'error': None
        }
        _save_job_status(job_id, job_status)
        
        logger.info(f"[/fix/start] Job status saved in {time.time() - start_time:.3f}s")
        
        # Run fix workflow in a separate thread to avoid blocking
        # This ensures the endpoint returns immediately
        _executor.submit(_run_fix_workflow_sync, job_id, request)
        
        elapsed = time.time() - start_time
        logger.info(f"[/fix/start] Returning response in {elapsed:.3f}s for job {job_id}")
        
        return {
            'job_id': job_id,
            'status': 'pending',
            'message': 'Fix workflow started. Poll /fix/job/{job_id} for status.',
            'response_time_ms': int(elapsed * 1000)
        }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[/fix/start] Failed after {elapsed:.3f}s: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job/{job_id}", dependencies=[Depends(get_current_user)])
async def get_job_status(job_id: str):
    """
    Get the status of an async fix job.
    
    Returns current status and result when completed.
    """
    job = _load_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    # If completed, return the full result
    if job['status'] == 'completed' and job.get('result'):
        return {
            **job,
            'result': job['result']
        }
    
    return job


@router.post("/continue", response_model=FixResult,
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def continue_fix_workflow(request: ContinueFixRequest):
    """
    Continue a fix workflow after user makes a choice.
    
    Used for mixed workflows where user needs to choose between:
    - library: Only apply package upgrades
    - code: Only apply code fixes
    - both: Apply both package upgrades and code fixes
    - skip: Skip this pattern
    """
    try:
        result = await fix_service.continue_fix_workflow(
            agent_id=request.agent_id,
            pattern_id=request.pattern_id,
            user_choice=request.user_choice,
            previous_result=request.previous_result
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ping", dependencies=[Depends(get_current_user)])
async def ping():
    """
    Simple ping endpoint for testing connectivity.
    
    Returns immediately - useful for diagnosing timeout issues.
    """
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "message": "Fix API is responsive"
    }


# ============================================================================
# Async Launch & Session Management Endpoints
# ============================================================================


@router.get("/health", dependencies=[Depends(get_current_user)])
async def health_check():
    """
    Health check endpoint that also performs cleanup.
    
    This endpoint:
    1. Returns health status
    2. Triggers cleanup of old resources (containers/images older than 30 min)
    
    Can be called by load balancers or monitoring systems.
    """
    try:
        # Perform cleanup (non-blocking, best effort)
        cleanup_result = fix_service.cleanup_old_resources(max_age_minutes=30)
        
        # Get active sessions count
        sessions = fix_service.get_active_sessions()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "active_sessions": sessions.get('total_count', 0),
            "cleanup": {
                "containers_removed": len(cleanup_result.get('containers_removed', [])),
                "images_removed": len(cleanup_result.get('images_removed', [])),
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }
