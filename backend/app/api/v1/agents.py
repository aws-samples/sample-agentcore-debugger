"""
Agent API endpoints
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core.security import get_current_user, require_role, Role, CurrentUser
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel
import boto3
import json
import uuid

from app.models.agent import (
    AgentListResponse, Agent, AgentHealthStatus, 
    AgentMetrics, AgentConfiguration
)
from app.services.agent_service import AgentService

router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(get_current_user)],  # All endpoints require authentication
)
agent_service = AgentService()


class TestDeployedAgentRequest(BaseModel):
    """Request to test a deployed agent"""
    agent_arn: str
    prompt: str
    session_id: Optional[str] = None


class TestDeployedAgentResult(BaseModel):
    """Result of testing a deployed agent"""
    status: str
    prompt: str
    response: Optional[str] = None
    parsed_response: Optional[Any] = None  # Can be dict, str, or any JSON type
    agent_arn: str
    session_id: str
    error: Optional[str] = None


@router.get("", response_model=AgentListResponse)
async def list_agents(
    status: Optional[str] = Query(None, description="Filter by status"),
    source: Optional[str] = Query(None, description="Filter by source"),
    search: Optional[str] = Query(None, description="Search by name or ID"),
    limit: int = Query(100, ge=1, le=1000, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    Get list of all agents with optional filters
    
    - **status**: Filter by agent status (ACTIVE, FAILED, etc.)
    - **source**: Filter by source (agentcore, lambda, etc.)
    - **search**: Search in agent name or ID
    - **limit**: Maximum number of results (default: 100)
    - **offset**: Pagination offset (default: 0)
    """
    return await agent_service.get_agents(
        status=status,
        source=source,
        search=search,
        limit=limit,
        offset=offset
    )


@router.get("/deployed")
async def list_deployed_agents(region: str = Query("us-east-1", description="AWS region")):
    """
    List all deployed agents in Amazon Bedrock AgentCore.
    
    - **region**: AWS region to query (default: us-east-1)
    """
    try:
        client = boto3.client('bedrock-agentcore-control', region_name=region)
        
        agents = []
        next_token = None
        
        # Paginate through all results
        while True:
            if next_token:
                response = client.list_agent_runtimes(nextToken=next_token)
            else:
                response = client.list_agent_runtimes()
            
            for agent in response.get('agentRuntimes', []):
                agents.append({
                    "name": agent.get('agentRuntimeName'),
                    "arn": agent.get('agentRuntimeArn'),
                    "id": agent.get('agentRuntimeId'),
                    "status": agent.get('status'),
                    "version": agent.get('agentRuntimeVersion'),
                    "lastUpdatedAt": agent.get('lastUpdatedAt').isoformat() if agent.get('lastUpdatedAt') else None
                })
            
            next_token = response.get('nextToken')
            if not next_token:
                break
        
        return {"agents": agents, "region": region}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list deployed agents: {str(e)}")


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str):
    """
    Get detailed information about a specific agent
    
    - **agent_id**: The agent identifier
    """
    agent = await agent_service.get_agent_by_id(agent_id)
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    
    return agent


@router.get("/{agent_id}/health", response_model=AgentHealthStatus)
async def get_agent_health(
    agent_id: str,
    source: str = Query(..., description="Agent source (agentcore, lambda, etc.)")
):
    """
    Get health status for a specific agent
    
    - **agent_id**: The agent identifier
    - **source**: The agent source type
    """
    try:
        return await agent_service.get_agent_health(agent_id, source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get health status: {str(e)}")


@router.get("/{agent_id}/metrics", response_model=AgentMetrics)
async def get_agent_metrics(
    agent_id: str,
    start_time: Optional[datetime] = Query(None, description="Start time for metrics"),
    end_time: Optional[datetime] = Query(None, description="End time for metrics")
):
    """
    Get ADOT metrics for a specific agent
    
    - **agent_id**: The agent identifier
    - **start_time**: Start time for metrics (default: 24 hours ago)
    - **end_time**: End time for metrics (default: now)
    """
    try:
        return await agent_service.get_agent_metrics(agent_id, start_time, end_time)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@router.get("/{agent_id}/configuration", response_model=AgentConfiguration)
async def get_agent_configuration(
    agent_id: str,
    source: str = Query(..., description="Agent source (agentcore, lambda, etc.)")
):
    """
    Get configuration for a specific agent
    
    - **agent_id**: The agent identifier
    - **source**: The agent source type
    """
    try:
        return await agent_service.get_agent_configuration(agent_id, source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get configuration: {str(e)}")


@router.post("/test-deployed", response_model=TestDeployedAgentResult)
async def test_deployed_agent(request: TestDeployedAgentRequest):
    """
    Test a prompt against a deployed agent in Amazon Bedrock AgentCore.
    
    - **agent_arn**: The full ARN of the deployed agent
    - **prompt**: The prompt to send to the agent
    - **session_id**: Optional session ID (will be generated if not provided)
    """
    try:
        # Generate session ID if not provided (must be 33+ chars)
        session_id = request.session_id or f"session-{uuid.uuid4().hex}-{uuid.uuid4().hex[:8]}"
        
        # Ensure session_id is at least 33 characters
        if len(session_id) < 33:
            session_id = session_id + "-" + uuid.uuid4().hex[:33 - len(session_id) - 1]
        
        # Extract region from ARN
        # Format: arn:aws:bedrock-agentcore:us-east-1:ACCOUNT:runtime/agent-name
        arn_parts = request.agent_arn.split(':')
        region = arn_parts[3] if len(arn_parts) > 3 else 'us-east-1'
        
        # Initialize the Bedrock AgentCore client
        client = boto3.client('bedrock-agentcore', region_name=region)
        
        # Prepare the payload
        payload = json.dumps({"prompt": request.prompt})
        
        # Invoke the agent (no qualifier - use default endpoint)
        response = client.invoke_agent_runtime(
            agentRuntimeArn=request.agent_arn,
            runtimeSessionId=session_id,
            payload=payload.encode('utf-8')
        )
        
        # Read the streaming response
        response_body = response['response'].read()
        response_text = response_body.decode('utf-8')
        
        # Try to parse as JSON
        parsed_response = None
        try:
            parsed_response = json.loads(response_text)
            # If the response contains a nested JSON string, parse it too
            if isinstance(parsed_response, dict) and 'response' in parsed_response:
                inner = parsed_response.get('response')
                if isinstance(inner, str):
                    try:
                        parsed_response['response'] = json.loads(inner)
                    except:
                        pass
        except:
            pass
        
        return TestDeployedAgentResult(
            status="success",
            prompt=request.prompt,
            response=response_text,
            parsed_response=parsed_response,
            agent_arn=request.agent_arn,
            session_id=session_id
        )
        
    except boto3.exceptions.Boto3Error as e:
        return TestDeployedAgentResult(
            status="error",
            prompt=request.prompt,
            agent_arn=request.agent_arn,
            session_id=request.session_id or "",
            error=f"AWS API error: {str(e)}"
        )
    except Exception as e:
        return TestDeployedAgentResult(
            status="error",
            prompt=request.prompt,
            agent_arn=request.agent_arn,
            session_id=request.session_id or "",
            error=f"Failed to invoke agent: {str(e)}"
        )


@router.post("/{agent_id}/generate-test-error")
async def generate_test_error(
    agent_id: str,
    error_type: str = Query(
        "order",
        description="Type of error to generate: order, score, recommend, status, module"
    ),
    agent_arn: Optional[str] = Query(None, description="Full agent ARN (preferred over agent_id)")
):
    """
    Generate a test error by invoking the deployed agent with specific prompts.
    
    This is useful for testing the error analysis and auto-fix workflow.
    Uses boto3 to invoke the agent via AWS API.
    
    Error types:
    - **order**: Triggers pandas deprecation error (df.append)
    - **score**: Triggers numpy deprecation error (np.int)
    - **recommend**: Triggers torch error (invalid ord parameter)
    - **status**: Triggers requests connection error
    - **module**: Triggers imported module exception (division by zero)
    """
    # Map error types to prompts that trigger them
    error_prompts = {
        "order": "Show me my order history",
        "score": "What is my customer score?",
        "recommend": "Recommend products for me",
        "status": "Check service status",
        "module": "test module error"
    }
    
    prompt = error_prompts.get(error_type, error_prompts["order"])
    region = 'us-east-1'
    
    try:
        # If agent_arn is provided, use it directly
        if agent_arn:
            final_agent_arn = agent_arn
            # Extract region from ARN
            arn_parts = agent_arn.split(':')
            if len(arn_parts) > 3:
                region = arn_parts[3]
        else:
            # Look up the actual ARN from AWS by matching agent name
            # Remove -DEFAULT suffix and normalize for matching
            agent_id_base = agent_id.replace('-DEFAULT', '').replace('-', '_').lower()
            
            control_client = boto3.client('bedrock-agentcore-control', region_name=region)
            response = control_client.list_agent_runtimes()
            
            final_agent_arn = None
            for agent in response.get('agentRuntimes', []):
                # Match by normalized name (case-insensitive, underscore/hyphen agnostic)
                agent_name = agent.get('agentRuntimeName', '').lower().replace('-', '_')
                agent_runtime_id = agent.get('agentRuntimeId', '').lower().replace('-', '_')
                
                if agent_name == agent_id_base or agent_runtime_id.startswith(agent_id_base):
                    final_agent_arn = agent.get('agentRuntimeArn')
                    break
            
            if not final_agent_arn:
                return {
                    "status": "error",
                    "agent_id": agent_id,
                    "error_type": error_type,
                    "message": f"Could not find deployed agent matching '{agent_id}'. Available agents: {[a.get('agentRuntimeName') for a in response.get('agentRuntimes', [])]}"
                }
        
        # Initialize the Bedrock AgentCore client
        agent_core_client = boto3.client('bedrock-agentcore', region_name=region)
        
        # Prepare the payload
        payload = json.dumps({"prompt": prompt}).encode()
        
        # Generate a unique session ID (must be 33+ chars)
        session_id = f"test-{uuid.uuid4().hex}-{uuid.uuid4().hex[:8]}"
        
        # Invoke the agent
        response = agent_core_client.invoke_agent_runtime(
            agentRuntimeArn=final_agent_arn,
            runtimeSessionId=session_id,
            payload=payload
        )
        
        # Process the response
        response_content = []
        content_type = response.get("contentType", "")
        
        if "text/event-stream" in content_type:
            # Handle streaming response
            for line in response["response"].iter_lines(chunk_size=10):
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        line = line[6:]
                    response_content.append(line)
        elif content_type == "application/json":
            # Handle standard JSON response
            for chunk in response.get("response", []):
                response_content.append(chunk.decode('utf-8'))
        else:
            response_content.append(str(response))
        
        response_text = "\n".join(response_content)
        
        return {
            "status": "invoked",
            "agent_id": agent_id,
            "error_type": error_type,
            "prompt": prompt,
            "message": f"Error generated successfully. You can now trace this error in the Error Analysis page.",
            "response": response_text[-2000:] if response_text else None,
            "agent_arn": final_agent_arn,
            "session_id": session_id
        }
        
    except boto3.exceptions.Boto3Error as e:
        return {
            "status": "error",
            "agent_id": agent_id,
            "error_type": error_type,
            "message": f"AWS API error: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "agent_id": agent_id,
            "error_type": error_type,
            "message": f"Failed to invoke agent: {str(e)}"
        }
