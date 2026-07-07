"""
Service layer for error analysis operations
"""
import sys
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from collections import Counter

# Add parent directory to path to import existing modules
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from src.collectors.cloudwatch_collector import CloudWatchCollector
from src.collectors.xray_collector import XRayCollector
from app.models.error import (
    LogEvent, ErrorSummary, ErrorAnalysis, 
    XRaySpan, TraceAnalysis, ErrorPattern
)


class ErrorService:
    """Service for error analysis operations"""
    
    def __init__(self, region: str = 'us-east-1'):
        self.cloudwatch = CloudWatchCollector(region=region)
        self.xray = XRayCollector(region=region)
    
    async def get_error_logs(
        self,
        agent_id: Optional[str] = None,
        log_group: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        error_type: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100
    ) -> List[LogEvent]:
        """Get error logs with filters"""
        
        # Default time range: last 24 hours
        if not end_time:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        if not start_time:
            start_time = end_time - timedelta(days=1)
        
        # Set log group based on agent_id or explicit log_group
        if log_group:
            self.cloudwatch.log_groups = [log_group]
        elif agent_id:
            # Use agent-specific log group (same as fix_service)
            agent_id_base = agent_id.replace('-DEFAULT', '')
            if agent_id.endswith('-DEFAULT'):
                primary_log_group = f"/aws/bedrock-agentcore/runtimes/{agent_id}"
            else:
                primary_log_group = f"/aws/bedrock-agentcore/runtimes/{agent_id}-DEFAULT"
            self.cloudwatch.log_groups = [primary_log_group]
        # If no agent_id, use discovered log groups (all agents)
        
        # Fetch and parse logs
        raw_events = self.cloudwatch.fetch_log_events(start_time, end_time)
        parsed_events = self.cloudwatch.parse_otel_logs(raw_events)
        
        # Apply filters
        filtered_events = []
        for event in parsed_events:
            # Filter by agent_id
            if agent_id and event.get('agent_id') != agent_id:
                # Also check if agent_id is in log_group name
                if agent_id not in event.get('log_group', ''):
                    continue
            
            # Filter by error_type
            if error_type and event.get('error_type') != error_type:
                continue
            
            # Filter by severity
            if severity and event.get('level', '').upper() != severity.upper():
                continue
            
            filtered_events.append(event)
        
        # Convert to LogEvent models
        log_events = []
        for event in filtered_events[:limit]:
            try:
                log_events.append(LogEvent(
                    timestamp=event.get('timestamp', datetime.now()),
                    log_group=event.get('log_group', 'unknown'),
                    log_stream=event.get('log_stream'),
                    level=event.get('level', 'UNKNOWN'),
                    message=event.get('message', ''),
                    body=event.get('body'),
                    trace_id=event.get('trace_id'),
                    span_id=event.get('span_id'),
                    service_name=event.get('service_name'),
                    agent_id=event.get('agent_id'),
                    session_id=event.get('session_id'),
                    error_type=event.get('error_type'),
                    stack_trace=event.get('stack_trace'),
                    error_message=event.get('error_message'),
                    raw_message=event.get('raw_message'),
                    structured_data=event.get('structured_data')
                ))
            except Exception as e:
                print(f"Error converting log event: {e}")
                continue
        
        return log_events
    
    async def analyze_errors(
        self,
        agent_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> ErrorAnalysis:
        """Analyze errors and return summary"""
        
        # Default time range
        if not end_time:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        if not start_time:
            start_time = end_time - timedelta(days=1)
        
        # Get all error logs
        logs = await self.get_error_logs(
            agent_id=agent_id,
            start_time=start_time,
            end_time=end_time,
            limit=1000
        )
        
        # Count by severity
        severity_counts = Counter()
        error_type_counts = Counter()
        affected_agents = set()
        affected_services = set()
        error_messages_by_type: Dict[str, List[str]] = {}
        
        total_errors = 0
        total_warnings = 0
        
        for log in logs:
            level = log.level.upper()
            severity_counts[level] += 1
            
            if level in ['ERROR', 'FATAL', 'CRITICAL']:
                total_errors += 1
            elif level in ['WARN', 'WARNING']:
                total_warnings += 1
            
            # Count by error type
            err_type = log.error_type or 'unknown'
            error_type_counts[err_type] += 1
            
            # Collect sample messages
            if err_type not in error_messages_by_type:
                error_messages_by_type[err_type] = []
            if len(error_messages_by_type[err_type]) < 3:
                error_messages_by_type[err_type].append(log.message[:200])
            
            # Track affected agents and services
            if log.agent_id:
                affected_agents.add(log.agent_id)
            if log.service_name:
                affected_services.add(log.service_name)
        
        # Build error summaries
        total_count = len(logs) or 1
        errors_by_type = []
        for err_type, count in error_type_counts.most_common():
            errors_by_type.append(ErrorSummary(
                error_type=err_type,
                count=count,
                percentage=round(count / total_count * 100, 2),
                sample_messages=error_messages_by_type.get(err_type, [])
            ))
        
        # Calculate error rate (errors per hour)
        hours = max((end_time - start_time).total_seconds() / 3600, 1)
        error_rate = round(total_errors / hours, 2)
        
        return ErrorAnalysis(
            total_errors=total_errors,
            total_warnings=total_warnings,
            error_rate=error_rate,
            time_range_start=start_time,
            time_range_end=end_time,
            errors_by_type=errors_by_type,
            errors_by_severity=dict(severity_counts),
            recent_errors=logs[:20],
            affected_agents=list(affected_agents),
            affected_services=list(affected_services)
        )
    
    async def get_trace_errors(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        filter_expression: Optional[str] = None
    ) -> TraceAnalysis:
        """Get X-Ray trace errors"""
        
        # Default time range
        if not end_time:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        if not start_time:
            start_time = end_time - timedelta(hours=6)
        
        # Fetch traces
        trace_summaries = self.xray.fetch_traces(start_time, end_time, filter_expression)
        
        if not trace_summaries:
            return TraceAnalysis(
                total_traces=0,
                total_segments=0,
                error_count=0,
                fault_count=0,
                avg_duration=0,
                min_duration=0,
                max_duration=0,
                service_performance={},
                error_spans=[]
            )
        
        # Get trace details
        trace_ids = [t.get('Id') for t in trace_summaries if t.get('Id')]
        trace_data = self.xray.get_trace_details(trace_ids[:50])  # Limit to 50
        
        # Extract error spans
        error_spans_data = self.xray.extract_error_spans(trace_data)
        
        # Analyze performance
        analysis = self.xray.analyze_trace_performance(trace_data)
        
        # Convert to XRaySpan models
        error_spans = []
        for span in error_spans_data[:100]:
            error_spans.append(XRaySpan(
                trace_id=span.get('trace_id', ''),
                segment_id=span.get('segment_id'),
                parent_id=span.get('parent_id'),
                name=span.get('name', 'Unknown'),
                start_time=span.get('start_time'),
                end_time=span.get('end_time'),
                duration=span.get('duration'),
                error=span.get('error', False),
                fault=span.get('fault', False),
                cause=span.get('cause'),
                annotations=span.get('annotations', {}),
                metadata=span.get('metadata', {}),
                service_name=span.get('service_name'),
                subsegment_name=span.get('subsegment_name'),
                http_status=span.get('http_status'),
                error_message=span.get('error_message'),
                exception_type=span.get('exception_type')
            ))
        
        return TraceAnalysis(
            total_traces=analysis.get('total_traces', 0),
            total_segments=analysis.get('total_segments', 0),
            error_count=analysis.get('error_count', 0),
            fault_count=analysis.get('fault_count', 0),
            avg_duration=analysis.get('avg_duration', 0),
            min_duration=analysis.get('min_duration', 0),
            max_duration=analysis.get('max_duration', 0),
            service_performance=analysis.get('service_performance', {}),
            error_spans=error_spans
        )
    
    async def detect_error_patterns(
        self,
        agent_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[ErrorPattern]:
        """Detect recurring error patterns"""
        
        logs = await self.get_error_logs(
            agent_id=agent_id,
            start_time=start_time,
            end_time=end_time,
            limit=500
        )
        
        # Group by error type and message similarity
        patterns: Dict[str, Dict] = {}
        
        for log in logs:
            err_type = log.error_type or 'unknown'
            # Create a simple pattern key from error type
            pattern_key = f"{err_type}"
            
            if pattern_key not in patterns:
                patterns[pattern_key] = {
                    'error_type': err_type,
                    'frequency': 0,
                    'first_seen': log.timestamp,
                    'last_seen': log.timestamp,
                    'sample_message': log.message[:500],
                    'affected_agents': set()
                }
            
            patterns[pattern_key]['frequency'] += 1
            patterns[pattern_key]['last_seen'] = max(
                patterns[pattern_key]['last_seen'], 
                log.timestamp
            )
            patterns[pattern_key]['first_seen'] = min(
                patterns[pattern_key]['first_seen'], 
                log.timestamp
            )
            if log.agent_id:
                patterns[pattern_key]['affected_agents'].add(log.agent_id)
        
        # Convert to ErrorPattern models
        result = []
        for idx, (key, data) in enumerate(sorted(
            patterns.items(), 
            key=lambda x: x[1]['frequency'], 
            reverse=True
        )):
            result.append(ErrorPattern(
                pattern_id=f"pattern_{idx}",
                error_type=data['error_type'],
                frequency=data['frequency'],
                first_seen=data['first_seen'],
                last_seen=data['last_seen'],
                sample_message=data['sample_message'],
                affected_agents=list(data['affected_agents']),
                suggested_fix=self._get_suggested_fix(data['error_type'])
            ))
        
        return result
    
    def _get_suggested_fix(self, error_type: str) -> Optional[str]:
        """Get suggested fix for error type"""
        fixes = {
            'rate_limit': 'Implement exponential backoff and retry logic. Consider increasing rate limits or distributing load.',
            'timeout': 'Increase timeout values or optimize the operation. Check for network latency issues.',
            'authentication': 'Verify credentials and IAM permissions. Check token expiration.',
            'permission': 'Review IAM policies and ensure proper permissions are granted.',
            'validation': 'Check input data format and required fields. Review API documentation.',
            'service_error': 'Check AWS service health dashboard. Implement retry with backoff.',
            'network': 'Check VPC configuration, security groups, and network connectivity.',
            'resource_not_found': 'Verify resource exists and ARN/ID is correct.',
            'configuration': 'Review agent configuration and environment variables.',
            'memory': 'Increase memory allocation or optimize memory usage.',
        }
        return fixes.get(error_type)
