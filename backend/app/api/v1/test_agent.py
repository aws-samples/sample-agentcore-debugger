"""
AgentCore Draft Testing API endpoints

Replaces local Docker testing with direct AgentCore Runtime deployment.
Flow: deploy draft → test via 'test' endpoint → promote or discard.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging

from app.core.security import get_current_user, require_role, Role
from app.services.agentcore_test_service import AgentCoreTestService
from app.services.codebuild_service import CodeBuildService
from app.services.sample_agent_service import SampleAgentService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/test-agent", tags=["test-agent"])

service = AgentCoreTestService()
build_service = CodeBuildService()
sample_service = SampleAgentService()


# ── Request models ───────────────────────────────────────────────────────

class BuildAndTestRequest(BaseModel):
    agent_runtime_id: str
    agent_name: str
    working_directory: str


class DeployFixedCodeRequest(BaseModel):
    """Deploy fixed code directly from fix job result (no filesystem dependency)."""
    agent_runtime_id: str
    agent_name: str
    fixed_files: Dict[str, str]  # filename -> content


class DeployDraftRequest(BaseModel):
    agent_runtime_id: str
    image_uri: str


class InvokeTestRequest(BaseModel):
    agent_runtime_arn: str
    prompt: str
    session_id: Optional[str] = None


class PromoteRequest(BaseModel):
    agent_runtime_id: str


class DiscardRequest(BaseModel):
    agent_runtime_id: str


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post("/build-and-test",
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def build_and_test(request: BuildAndTestRequest) -> Dict[str, Any]:
    """
    One-click: build fixed code → push to ECR → deploy as draft on AgentCore.

    Returns a build_id to poll for progress via /build-status/{build_id}.
    Steps shown to user: packaging → uploading → building → deploying → ready.
    """
    return await build_service.build_and_deploy_draft(
        agent_runtime_id=request.agent_runtime_id,
        working_directory=request.working_directory,
        agent_name=request.agent_name,
    )


@router.post("/deploy-fixed-code",
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def deploy_fixed_code(request: DeployFixedCodeRequest) -> Dict[str, Any]:
    """
    Deploy fixed code directly to AgentCore Runtime.

    Accepts fixed file contents (from fix job result), packages them,
    uploads to S3, and updates the agent runtime. No filesystem dependency.
    This is the reliable path — works regardless of ECS task restarts.
    """
    return await build_service.deploy_from_fixed_files(
        agent_runtime_id=request.agent_runtime_id,
        agent_name=request.agent_name,
        fixed_files=request.fixed_files,
    )


@router.get("/build-status/{build_id}",
            dependencies=[Depends(get_current_user)])
async def get_build_status(build_id: str) -> Dict[str, Any]:
    """
    Poll build progress. Phases: preparing → packaging → uploading → building → deploying → ready.
    """
    return await build_service.get_build_status(build_id)


@router.post("/deploy-draft",
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def deploy_draft(request: DeployDraftRequest) -> Dict[str, Any]:
    """
    Deploy fixed code as a new draft version on AgentCore.

    Creates a new immutable version and points a 'test' endpoint to it.
    Production (DEFAULT endpoint) is NOT affected.
    """
    return await service.deploy_draft(
        agent_runtime_id=request.agent_runtime_id,
        image_uri=request.image_uri,
    )


@router.post("/invoke",
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def invoke_test(request: InvokeTestRequest) -> Dict[str, Any]:
    """
    Send a prompt to the agent's 'test' endpoint.

    This invokes the draft version only — production traffic is unaffected.
    """
    return await service.invoke_test(
        agent_runtime_arn=request.agent_runtime_arn,
        prompt=request.prompt,
        session_id=request.session_id,
    )


@router.post("/promote",
             dependencies=[Depends(require_role(Role.ADMIN))])
async def promote_to_production(request: PromoteRequest) -> Dict[str, Any]:
    """
    Promote the tested draft version to production (DEFAULT endpoint).

    Only admins can promote to production.
    """
    return await service.promote_to_production(
        agent_runtime_id=request.agent_runtime_id,
    )


@router.post("/discard",
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def discard_draft(request: DiscardRequest) -> Dict[str, Any]:
    """
    Discard the draft — delete the test endpoint.

    Production stays on its current version.
    """
    return await service.discard_draft(
        agent_runtime_id=request.agent_runtime_id,
    )


@router.get("/status/{agent_runtime_id}",
            dependencies=[Depends(get_current_user)])
async def get_test_status(agent_runtime_id: str) -> Dict[str, Any]:
    """
    Get the status of the test and production endpoints.
    """
    return await service.get_test_status(
        agent_runtime_id=agent_runtime_id,
    )


# ── Sample/Demo agent ────────────────────────────────────────────────────

@router.post("/deploy-sample",
             dependencies=[Depends(require_role(Role.OPERATOR))])
async def deploy_sample_agent() -> Dict[str, Any]:
    """
    Deploy the bundled sample (demo) agent so users can try the debugger
    on a known-buggy agent before using it on their real agents.

    Uses direct code deployment (zip → S3 → AgentCore). Idempotent — repeat
    calls update the existing sample agent instead of creating duplicates.
    """
    return await sample_service.deploy_sample()


@router.get("/sample-status",
            dependencies=[Depends(get_current_user)])
async def get_sample_status() -> Dict[str, Any]:
    """Check whether the sample agent is deployed and its status."""
    return await sample_service.get_sample_status()
