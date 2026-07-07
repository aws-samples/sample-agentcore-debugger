"""
Pydantic models for Agent-related data
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class AgentStatus(str, Enum):
    """Agent status enum"""
    ACTIVE = "ACTIVE"
    READY = "READY"  # AgentCore runtime status
    PREPARED = "PREPARED"
    CREATING = "CREATING"
    UPDATING = "UPDATING"
    FAILED = "FAILED"
    ERROR = "ERROR"
    DELETING = "DELETING"
    UNKNOWN = "UNKNOWN"


class AgentSource(str, Enum):
    """Agent source enum"""
    AGENTCORE = "agentcore"
    AGENTCORE_RUNTIME = "agentcore-runtime"
    LAMBDA = "lambda"
    ECS = "ecs"
    EC2 = "ec2"
    CLOUDWATCH = "cloudwatch"
    UNKNOWN = "unknown"


class AgentBase(BaseModel):
    """Base agent model"""
    agent_id: str
    name: str
    status: AgentStatus
    source: AgentSource


class Agent(AgentBase):
    """Full agent model"""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    log_group: Optional[str] = None
    stored_bytes: Optional[int] = None
    runtime: Optional[str] = None
    memory_size: Optional[int] = None
    timeout: Optional[int] = None


class AgentListResponse(BaseModel):
    """Response for agent list endpoint"""
    agents: List[Agent]
    total: int
    active: int
    errors: int
    runtime_count: int


class AgentHealthStatus(BaseModel):
    """Agent health status"""
    status: str = Field(..., description="healthy, degraded, or error")
    error_rate: float = Field(..., description="Error rate percentage")
    avg_response_time: float = Field(..., description="Average response time in ms")


class AgentMetrics(BaseModel):
    """Agent metrics from ADOT"""
    runtime_sessions: int = 0
    runtime_invocations: int = 0
    runtime_errors: int = 0
    runtime_faults: int = 0
    runtime_throttles: int = 0
    runtime_error_rate: float = 0.0
    runtime_throttle_rate: float = 0.0
    vcpu_consumption_hours: float = 0.0
    memory_consumption_gb_hours: float = 0.0
    avg_duration_seconds: float = 0.0
    max_duration_seconds: float = 0.0
    min_duration_seconds: float = 0.0
    recent_invocations: List[Dict[str, Any]] = []


class AgentConfiguration(BaseModel):
    """Agent configuration"""
    config: Dict[str, Any]
