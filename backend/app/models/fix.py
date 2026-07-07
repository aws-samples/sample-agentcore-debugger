"""
Pydantic models for fix operations
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class FixStatus(str, Enum):
    """Status of a fix operation"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    AWAITING_CHOICE = "awaiting_choice"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowType(str, Enum):
    """Type of fix workflow"""
    PACKAGE_ONLY = "package_only"
    CODE_FIX = "code_fix_required"
    MIXED = "mixed"


class UserChoice(str, Enum):
    """User choice for mixed workflow"""
    LIBRARY = "library"
    CODE = "code"
    BOTH = "both"
    SKIP = "skip"


class SampleEvent(BaseModel):
    """Sample error event"""
    timestamp: Optional[datetime] = None
    message: str = ""
    trace_id: Optional[str] = None


class ErrorCluster(BaseModel):
    """Clustered error pattern"""
    pattern_id: str
    error_type: str
    error_message: str
    count: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    sample_events: List[SampleEvent] = []
    stack_trace: Optional[str] = None
    affected_files: List[str] = []
    status: FixStatus = FixStatus.PENDING
    
    class Config:
        use_enum_values = True


class SuppressedError(BaseModel):
    """Info about a suppressed (deduplicated) error"""
    message: str
    original_count: int
    suppressed_count: int
    error_type: str = "unknown"
    severity: str = "unknown"


class SuppressionSummary(BaseModel):
    """Summary of error deduplication/suppression"""
    total_original_errors: int = 0
    total_unique_patterns: int = 0
    total_suppressed: int = 0
    suppression_rate: float = 0.0
    top_suppressed_errors: List[SuppressedError] = []


class ErrorClustersResponse(BaseModel):
    """Response containing error clusters and suppression summary"""
    clusters: List[ErrorCluster] = []
    suppression_summary: SuppressionSummary = SuppressionSummary()


class FixRequest(BaseModel):
    """Request to start a fix workflow"""
    agent_id: str
    pattern_id: str
    error_cluster: ErrorCluster
    user_choice: Optional[UserChoice] = None
    is_fix_all: bool = False  # If True, use shared workspace (Fix All mode)
    fix_all_session_id: Optional[str] = None  # Unique session ID for Fix All workspace isolation
    pre_analysis: Optional[Dict[str, Any]] = None  # Pre-computed analysis from /analyze endpoint (avoids redundant classification)
    
    class Config:
        use_enum_values = True


class ContinueFixRequest(BaseModel):
    """Request to continue a fix workflow with user choice"""
    agent_id: str
    pattern_id: str
    user_choice: UserChoice
    previous_result: Dict[str, Any] = {}
    
    class Config:
        use_enum_values = True


class FixResult(BaseModel):
    """Result of a fix operation"""
    pattern_id: str
    status: FixStatus
    workflow_type: WorkflowType = WorkflowType.CODE_FIX
    fixed_files: Dict[str, str] = {}
    original_files: Dict[str, str] = {}  # Original file contents for diff comparison
    code_agent_summary: str = ""
    package_recommendations: List[Dict[str, Any]] = []
    library_agent_output: str = ""
    git_info: Optional[Dict[str, Any]] = None
    working_directory: str = ""
    error_classification: Dict[str, Any] = {}
    user_options: List[str] = []
    message: str = ""
    
    class Config:
        use_enum_values = True


class TestLocallyRequest(BaseModel):
    """Request to test code locally"""
    agent_id: str
    working_directory: str


class DownloadConfigRequest(BaseModel):
    """Request to download S3 config"""
    agent_id: str
    working_directory: str
    s3_path: str


class DownloadConfigResult(BaseModel):
    """Result of downloading S3 config"""
    status: str
    config_path: str = ""
    files_in_directory: List[str] = []
    error: Optional[str] = None


class LaunchAgentRequest(BaseModel):
    """Request to launch agent locally"""
    agent_id: str
    working_directory: str
    session_id: Optional[str] = None  # Unique ID per user/browser session


class LaunchAgentResult(BaseModel):
    """Result of launching agent locally"""
    status: str
    agent_url: str = ""
    log_file_path: str = ""
    agent_name: str = ""
    container_name: str = ""  # Return container name for test_prompt to use
    message: str = ""
    error: Optional[str] = None


class TestPromptRequest(BaseModel):
    """Request to test a prompt against running agent"""
    agent_id: str
    working_directory: str
    prompt: str
    session_id: Optional[str] = None  # Must match the session_id used in launch


class TestPromptResult(BaseModel):
    """Result of testing a prompt"""
    status: str
    prompt: str = ""
    response: Optional[Dict[str, Any]] = None
    raw_output: str = ""
    error: Optional[str] = None


class StopAgentRequest(BaseModel):
    """Request to stop running agent"""
    agent_id: str
    working_directory: str
    session_id: Optional[str] = None  # If provided, stops only this session's container


class StopAgentResult(BaseModel):
    """Result of stopping agent"""
    status: str
    message: str = ""
    stopped_containers: List[str] = []
    error: Optional[str] = None


class TestLocallyResult(BaseModel):
    """Result of local testing (legacy)"""
    status: str
    test_output: str = ""
    container_logs: str = ""
    error: Optional[str] = None


class ErrorAnalysisRequest(BaseModel):
    """Request to analyze an error"""
    agent_id: str
    error_cluster: ErrorCluster


class ErrorAnalysisResult(BaseModel):
    """Result of error analysis"""
    status: str
    analysis: Dict[str, Any] = {}
    classification: Dict[str, Any] = {}
    recommendations: List[str] = []
    suggested_fix: Optional[str] = None
    confidence: float = 0.0
    error: Optional[str] = None


class LaunchStatus(str, Enum):
    """Status of async agent launch"""
    PENDING = "pending"
    CONFIGURING = "configuring"
    BUILDING = "building"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


class LaunchAgentAsyncResult(BaseModel):
    """Result of starting async agent launch"""
    status: str
    launch_id: str  # Unique ID to poll for status
    session_id: str  # Session ID for this launch
    message: str = ""


class LaunchStatusResult(BaseModel):
    """Status of an async agent launch"""
    status: str  # pending, configuring, building, starting, ready, failed
    launch_id: str
    session_id: str
    agent_url: str = ""
    agent_name: str = ""
    container_name: str = ""
    log_file_path: str = ""
    progress_message: str = ""
    error: Optional[str] = None


class ContainerStatusResult(BaseModel):
    """Status of a running container"""
    status: str  # running, stopped, not_found
    container_name: str
    session_id: str = ""
    agent_url: str = ""
    created_at: str = ""
    uptime_seconds: int = 0
    is_healthy: bool = False


class CleanupResult(BaseModel):
    """Result of cleanup operation"""
    status: str
    containers_removed: List[str] = []
    images_removed: List[str] = []
    message: str = ""


class ActiveSessionsResult(BaseModel):
    """List of active test sessions"""
    sessions: List[Dict[str, Any]] = []
    total_count: int = 0
