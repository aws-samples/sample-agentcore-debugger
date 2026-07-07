"""
Pydantic models for error analysis
"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class ErrorSeverity(str, Enum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARN = "WARN"
    WARNING = "WARNING"
    INFO = "INFO"
    UNKNOWN = "UNKNOWN"


class ErrorType(str, Enum):
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    VALIDATION = "validation"
    SERVICE_ERROR = "service_error"
    NETWORK = "network"
    PERMISSION = "permission"
    RESOURCE_NOT_FOUND = "resource_not_found"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    MEMORY = "memory"
    DISK = "disk"
    DATABASE = "database"
    GENERIC_ERROR = "generic_error"
    UNKNOWN = "unknown"


class LogEvent(BaseModel):
    """Parsed log event"""
    timestamp: datetime
    log_group: str
    log_stream: Optional[str] = None
    level: str
    message: str
    body: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    service_name: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None
    error_message: Optional[str] = None
    raw_message: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None


class ErrorSummary(BaseModel):
    """Summary of errors by type"""
    error_type: str
    count: int
    percentage: float
    sample_messages: List[str] = []


class ErrorAnalysis(BaseModel):
    """Complete error analysis response"""
    total_errors: int
    total_warnings: int
    error_rate: float
    time_range_start: datetime
    time_range_end: datetime
    errors_by_type: List[ErrorSummary]
    errors_by_severity: Dict[str, int]
    recent_errors: List[LogEvent]
    affected_agents: List[str]
    affected_services: List[str]


class XRaySpan(BaseModel):
    """X-Ray trace span with error info"""
    trace_id: str
    segment_id: Optional[str] = None
    parent_id: Optional[str] = None
    name: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None
    error: bool = False
    fault: bool = False
    cause: Optional[Any] = None
    annotations: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}
    service_name: Optional[str] = None
    subsegment_name: Optional[str] = None
    http_status: Optional[int] = None
    error_message: Optional[str] = None
    exception_type: Optional[str] = None


class TraceAnalysis(BaseModel):
    """X-Ray trace analysis response"""
    total_traces: int
    total_segments: int
    error_count: int
    fault_count: int
    avg_duration: float
    min_duration: float
    max_duration: float
    service_performance: Dict[str, Dict[str, Any]]
    error_spans: List[XRaySpan]


class ErrorPattern(BaseModel):
    """Detected error pattern"""
    pattern_id: str
    error_type: str
    frequency: int
    first_seen: datetime
    last_seen: datetime
    sample_message: str
    affected_agents: List[str]
    suggested_fix: Optional[str] = None
