"""
CloudWatch Logs Collector for AgentCore Debugger Assistant
"""
import boto3
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

def to_timestamp_ms(dt):
    """Convert datetime to millisecond timestamp, treating naive datetimes as UTC"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class CloudWatchCollector:
    """Collects and processes logs from AWS CloudWatch"""
    
    def __init__(self, region: str = 'us-east-1'):
        """Initialize CloudWatch collector
        
        Args:
            region: AWS region for CloudWatch client
        """
        self.region = region
        self.client = boto3.client('logs', region_name=region)
        
        # Default log groups to monitor for AgentCore and Bedrock Agents
        self.log_groups = [
            # AgentCore runtime logs (discovered patterns)
            '/aws/bedrock-agentcore/runtimes',  # Will search with prefix
            # Spans for tracing
            'aws/spans',  # Found active spans here
            # Traditional Bedrock Agent logs
            '/aws/bedrock/agent',
            # Lambda-based agents
            '/aws/lambda/agentcore',
            # Strands agents
            'agents/strands-agent-logs',
            # Generic patterns
            'bedrock-agentcore'
        ]
    
    def fetch_log_events(self, start_time: datetime, end_time: datetime, 
                        filter_pattern: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch log events from CloudWatch with error filtering
        
        Args:
            start_time: Start time for log search
            end_time: End time for log search
            filter_pattern: CloudWatch filter pattern for logs
            
        Returns:
            List of log events
        """
        events = []
        
        # Use specific log groups if set, otherwise discover all agent log groups
        if hasattr(self, 'log_groups') and self.log_groups and len(self.log_groups) < 10:
            # If log_groups has been specifically set to a small number (like 1 agent), use those
            target_log_groups = self.log_groups
        else:
            # Otherwise discover all agent log groups
            target_log_groups = self._discover_agent_log_groups()
        
        for log_group in target_log_groups:
            try:
                # Use filter_log_events with interleaved=True for proper time ordering
                # This ensures we get events sorted by timestamp across all streams
                response = self.client.filter_log_events(
                    logGroupName=log_group,
                    startTime=to_timestamp_ms(start_time),
                    endTime=to_timestamp_ms(end_time),
                    filterPattern=filter_pattern or '{ $.severityText = "WARN" || $.severityText = "ERROR" || $.severityText = "FATAL" || $.level = "WARN" || $.level = "ERROR" || $.level = "FATAL" }',
                    interleaved=True,  # Sort by timestamp across all streams
                    limit=10000  # Get up to 10000 events per request
                )
                
                # Add log group info to events
                for event in response.get('events', []):
                    event['logGroup'] = log_group
                    events.append(event)
                
                # Handle pagination to get ALL events (no artificial limit)
                while 'nextToken' in response:
                    response = self.client.filter_log_events(
                        logGroupName=log_group,
                        startTime=to_timestamp_ms(start_time),
                        endTime=to_timestamp_ms(end_time),
                        filterPattern=filter_pattern or '{ $.severityText = "WARN" || $.severityText = "ERROR" || $.severityText = "FATAL" || $.level = "WARN" || $.level = "ERROR" || $.level = "FATAL" }',
                        nextToken=response['nextToken'],
                        interleaved=True,
                        limit=10000
                    )
                    for event in response.get('events', []):
                        event['logGroup'] = log_group
                        events.append(event)
                    
                    # Safety limit to prevent infinite loops
                    if len(events) > 50000:
                        logger.warning(f"Reached safety limit (50k events) for log group {log_group}")
                        break
                    
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'ResourceNotFoundException':
                    # Log group doesn't exist, skip silently
                    continue
                else:
                    logger.warning(f"Could not access log group {log_group}: {e}")
        
        return sorted(events, key=lambda x: x['timestamp'], reverse=True)
    
    def _discover_agent_log_groups(self) -> List[str]:
        """Discover actual log groups that match AgentCore patterns"""
        discovered_groups = []
        
        try:
            # Get all log groups
            paginator = self.client.get_paginator('describe_log_groups')
            
            for page in paginator.paginate():
                for log_group in page.get('logGroups', []):
                    log_group_name = log_group['logGroupName']
                    
                    # Check if this log group matches our patterns
                    if any(pattern in log_group_name for pattern in [
                        'bedrock-agentcore',
                        'bedrock/agent',
                        'lambda/agentcore',
                        'strands-agent',
                        'spans/default'
                    ]):
                        discovered_groups.append(log_group_name)
            
            # Also add our static log groups if they exist
            for log_group in self.log_groups:
                if log_group not in discovered_groups:
                    try:
                        self.client.describe_log_groups(logGroupNamePrefix=log_group, limit=1)
                        response = self.client.describe_log_groups(logGroupNamePrefix=log_group)
                        for lg in response.get('logGroups', []):
                            if lg['logGroupName'] not in discovered_groups:
                                discovered_groups.append(lg['logGroupName'])
                    except ClientError:
                        continue
        
        except ClientError as e:
            logger.warning(f"Could not discover log groups: {e}")
            # Fallback to static list
            return self.log_groups
        
        logger.debug(f"Discovered {len(discovered_groups)} log groups: {discovered_groups}")
        
        return discovered_groups
    
    def parse_otel_logs(self, log_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse OpenTelemetry structured logs and filter for errors/warnings
        
        Args:
            log_events: Raw log events from CloudWatch
            
        Returns:
            List of parsed log events with structured data (errors and warnings only)
        """
        parsed_events = []
        
        for event in log_events:
            try:
                # Try to parse as JSON (structured logs)
                if event['message'].strip().startswith('{'):
                    log_data = json.loads(event['message'])
                    # Extract level from multiple possible fields
                    level = (log_data.get('level') or 
                            log_data.get('severityText') or 
                            log_data.get('severity') or 'INFO')
                    
                    # Extract message from multiple possible fields
                    # Prioritize errorMessage for actual error details, then fallback to other fields
                    error_message = log_data.get('errorMessage', '')
                    if error_message:
                        # Use the detailed error message as the primary message
                        message = error_message
                        body_field = error_message
                    else:
                        # Fallback to standard message fields
                        message = (log_data.get('message') or 
                                  log_data.get('body') or 
                                  log_data.get('msg') or '')
                        body_field = log_data.get('body', '')
                    
                    # Use the module-level datetime import explicitly
                    import sys
                    dt_module = sys.modules.get('datetime')
                    if dt_module:
                        timestamp = dt_module.datetime.fromtimestamp(event['timestamp'] / 1000)
                    else:
                        # Fallback: re-import
                        from datetime import datetime as dt_class
                        timestamp = dt_class.fromtimestamp(event['timestamp'] / 1000)
                    
                    parsed_event = {
                        'timestamp': timestamp,
                        'log_group': event.get('logGroup', 'unknown'),
                        'log_stream': event.get('logStream', 'unknown'),
                        'level': level,
                        'message': message,
                        'body': body_field,  # Preserve original body field
                        'trace_id': log_data.get('trace_id') or log_data.get('traceId'),
                        'span_id': log_data.get('span_id') or log_data.get('spanId'),
                        'service_name': log_data.get('service.name') or log_data.get('serviceName'),
                        'agent_id': log_data.get('agent.id') or log_data.get('agentId'),
                        'session_id': log_data.get('session.id') or log_data.get('sessionId'),
                        'error_type': (log_data.get('errorType') or 
                                      log_data.get('error.type') or 
                                      self._extract_error_type_from_structured_log(log_data) or
                                      self._extract_error_type(message)),
                        'stack_trace': log_data.get('stackTrace') or log_data.get('error.stack'),
                        'error_message': log_data.get('errorMessage', ''),  # Add explicit error message field
                        'raw_message': event['message'],
                        'structured_data': log_data  # Keep the full structured data for reference
                    }
                else:
                    # Handle plain text logs
                    # Use the module-level datetime import explicitly
                    import sys
                    dt_module = sys.modules.get('datetime')
                    if dt_module:
                        timestamp = dt_module.datetime.fromtimestamp(event['timestamp'] / 1000)
                    else:
                        from datetime import datetime as dt_class
                        timestamp = dt_class.fromtimestamp(event['timestamp'] / 1000)
                    
                    parsed_event = {
                        'timestamp': timestamp,
                        'log_group': event.get('logGroup', 'unknown'),
                        'log_stream': event.get('logStream', 'unknown'),
                        'level': self._extract_log_level(event['message']),
                        'message': event['message'],
                        'body': event['message'],  # For plain text, body is same as message
                        'trace_id': self._extract_trace_id(event['message']),
                        'span_id': None,
                        'service_name': self._extract_service_name(event.get('logGroup', '')),
                        'agent_id': self._extract_agent_id(event['message']),
                        'session_id': self._extract_session_id(event['message']),
                        'error_type': self._extract_error_type(event['message']),
                        'stack_trace': None,
                        'raw_message': event['message']
                    }
                
                parsed_events.append(parsed_event)
                
            except json.JSONDecodeError:
                # Fallback for malformed JSON
                import sys
                dt_module = sys.modules.get('datetime')
                if dt_module:
                    timestamp = dt_module.datetime.fromtimestamp(event['timestamp'] / 1000)
                else:
                    from datetime import datetime as dt_class
                    timestamp = dt_class.fromtimestamp(event['timestamp'] / 1000)
                
                parsed_events.append({
                    'timestamp': timestamp,
                    'log_group': event.get('logGroup', 'unknown'),
                    'log_stream': event.get('logStream', 'unknown'),
                    'level': 'UNKNOWN',
                    'message': event['message'],
                    'body': event['message'],  # For fallback, body is same as message
                    'trace_id': None,
                    'span_id': None,
                    'service_name': None,
                    'agent_id': None,
                    'session_id': None,
                    'error_type': None,
                    'stack_trace': None,
                    'raw_message': event['message']
                })
            except Exception as e:
                # Silently skip malformed events - don't spam the UI
                import logging
                logging.warning(f"Error parsing log event: {e}")
                continue
        
        # Comprehensive filtering: Include ALL warnings and errors
        filtered_events = []
        for event in parsed_events:
            should_include = False
            
            # PRIMARY: Include if log level indicates any issue (WARN or above)
            level = event.get('level', '').upper()
            if level in ['ERROR', 'WARN', 'WARNING', 'FATAL', 'CRITICAL', 'SEVERE']:
                should_include = True
            
            # SECONDARY: Include if error_type is meaningful (not unknown/None)
            error_type = event.get('error_type')
            if error_type and error_type not in ['unknown', None, '']:
                should_include = True
            
            # TERTIARY: Include if structured data contains exception information
            structured_data = event.get('structured_data', {})
            if structured_data:
                # Check for exception fields in attributes
                attributes = structured_data.get('attributes', {})
                if any(key.startswith('exception.') for key in attributes.keys()):
                    should_include = True
                
                # Check for error fields anywhere in the structured data
                if any('error' in str(key).lower() or 'exception' in str(key).lower() 
                       for key in attributes.keys()):
                    should_include = True
            
            # QUATERNARY: Include if message contains ANY error/warning indicators (comprehensive list)
            message = event.get('message', '').lower()
            comprehensive_error_keywords = [
                # Rate limiting and throttling
                'rate limit', 'rate-limit', 'throttle', 'throttling', 'quota exceeded', 'too many requests',
                # Timeouts and delays
                'timeout', 'timed out', 'deadline exceeded', 'connection timeout', 'request timeout',
                # Authentication and authorization
                'unauthorized', 'forbidden', 'access denied', 'permission denied', 'invalid token', 'auth failed',
                # General errors
                'error', 'exception', 'failed', 'failure', 'fatal', 'critical', 'severe',
                # Network and connectivity
                'connection refused', 'network error', 'dns resolution', 'connection failed',
                # Service issues
                'service unavailable', 'internal server error', 'bad gateway', 'service error',
                # Validation and input
                'invalid', 'malformed', 'bad request', 'validation error', 'parse error',
                # Resource issues
                'not found', 'does not exist', 'resource not found', 'out of memory', 'disk full',
                # Configuration issues
                'misconfigured', 'configuration error', 'config error', 'missing configuration',
                # Warnings
                'warning', 'warn', 'deprecated', 'obsolete', 'retry', 'retrying', 'fallback'
            ]
            
            if any(keyword in message for keyword in comprehensive_error_keywords):
                should_include = True
            
            # FALLBACK: Include if raw message contains error patterns (for unstructured logs)
            raw_message = event.get('raw_message', '').lower()
            if raw_message != message and any(keyword in raw_message for keyword in comprehensive_error_keywords):
                should_include = True
            
            # EXCLUDE: Skip obvious non-error logs to reduce noise
            if should_include:
                # Skip if it's clearly just informational despite containing keywords
                exclude_patterns = [
                    'successfully', 'completed successfully', 'operation successful',
                    'started successfully', 'initialized successfully', 'connected successfully',
                    'error handling completed', 'error processing completed', 'error resolved',
                    'error fixed', 'error corrected', 'no error', 'without error'
                ]
                
                # Only exclude if the message is clearly positive AND not explicitly ERROR/WARN level
                is_positive = any(pattern in message for pattern in exclude_patterns)
                if is_positive and level not in ['ERROR', 'WARN', 'WARNING', 'FATAL', 'CRITICAL']:
                    should_include = False
                
                # EXCLUDE: OpenTelemetry SDK/instrumentation noise
                # These are warnings from the OTEL SDK itself, not actual agent runtime errors
                # They appear in all agents and are not actionable by fixing agent code
                otel_sdk_noise = [
                    'attempting to instrument while already instrumented',
                    'already been instrumented',
                    'instrumentor already instrumented',
                    'skipping instrumentation',
                ]
                if any(noise in message for noise in otel_sdk_noise):
                    should_include = False
            
            if should_include:
                filtered_events.append(event)
        
        return filtered_events
    
    def _extract_log_level(self, message: str) -> str:
        """Extract log level from plain text message"""
        message_upper = message.upper()
        
        # Check for explicit log levels with word boundaries (more precise)
        import re
        for level in ['FATAL', 'ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE']:
            # Look for level at start of message or after timestamp/prefix
            pattern = rf'\b{level}\b'
            if re.search(pattern, message_upper):
                # Additional check: make sure it's not part of a success message
                if level in ['ERROR', 'FATAL'] and any(success_word in message_upper for success_word in ['SUCCESSFULLY', 'COMPLETED', 'SUCCESS', 'RESOLVED', 'FIXED']):
                    continue
                return level
        
        # Check for error indicators that suggest ERROR level (but not in success contexts)
        if not any(success_word in message_upper for success_word in ['SUCCESSFULLY', 'COMPLETED', 'SUCCESS', 'RESOLVED', 'FIXED']):
            error_indicators = ['FAILED', 'FAILURE', 'EXCEPTION', 'TIMEOUT', 'DENIED', 'REFUSED', 'INVALID', 'FORBIDDEN', 'UNAUTHORIZED', 'THROTTLED', 'RATE LIMIT', 'QUOTA EXCEEDED']
            if any(indicator in message_upper for indicator in error_indicators):
                return 'ERROR'
            
            # Check for warning indicators
            warning_indicators = ['DEPRECATED', 'RETRY', 'RETRYING', 'SLOW', 'DEGRADED']
            if any(indicator in message_upper for indicator in warning_indicators):
                return 'WARN'
        
        return 'INFO'
    
    def _extract_trace_id(self, message: str) -> Optional[str]:
        """Extract trace ID from message using common patterns"""
        import re
        
        # Common trace ID patterns
        patterns = [
            r'trace[_-]?id[:\s=]+([a-f0-9-]{32,})',
            r'traceId[:\s=]+([a-f0-9-]{32,})',
            r'trace[:\s=]+([a-f0-9-]{32,})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_service_name(self, log_group: str) -> Optional[str]:
        """Extract service name from log group"""
        if 'strands' in log_group:
            return 'strands-agent'
        elif 'bedrock' in log_group:
            return 'bedrock-agent'
        elif 'lambda' in log_group:
            return 'lambda-agent'
        return None
    
    def _extract_agent_id(self, message: str) -> Optional[str]:
        """Extract agent ID from message"""
        import re
        
        patterns = [
            r'agent[_-]?id[:\s=]+([a-zA-Z0-9-]+)',
            r'agentId[:\s=]+([a-zA-Z0-9-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_session_id(self, message: str) -> Optional[str]:
        """Extract session ID from message"""
        import re
        
        patterns = [
            r'session[_-]?id[:\s=]+([a-zA-Z0-9-]+)',
            r'sessionId[:\s=]+([a-zA-Z0-9-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_error_type(self, message: str) -> Optional[str]:
        """Extract error type from message"""
        message_lower = message.lower()
        
        error_types = {
            'timeout': ['timeout', 'timed out', 'deadline exceeded', 'request timeout', 'connection timeout'],
            'authentication': ['unauthorized', 'forbidden', 'invalid token', 'auth failed', 'authentication error', 'invalid credentials'],
            'rate_limit': ['rate limit', 'rate-limit', 'throttled', 'throttling', 'quota exceeded', 'too many requests', 'rate exceeded'],
            'validation': ['validation error', 'invalid input', 'bad request', 'invalid parameter', 'malformed request'],
            'service_error': ['internal server error', 'service unavailable', 'server error', 'service error', 'internal error'],
            'network': ['connection refused', 'network error', 'dns resolution', 'connection failed', 'network timeout'],
            'permission': ['access denied', 'permission denied', 'insufficient permissions', 'not authorized', 'forbidden access'],
            'resource_not_found': ['not found', 'resource not found', 'does not exist', '404'],
            'configuration': ['configuration error', 'config error', 'misconfigured', 'invalid configuration'],
            'dependency': ['dependency error', 'external service', 'downstream error', 'upstream error'],
            'memory': ['out of memory', 'memory error', 'heap space', 'memory limit'],
            'disk': ['disk full', 'no space left', 'disk error', 'storage error'],
            'database': ['database error', 'db error', 'connection pool', 'sql error', 'query failed']
        }
        
        for error_type, patterns in error_types.items():
            if any(pattern in message_lower for pattern in patterns):
                return error_type
        
        # Check for generic error indicators
        generic_error_patterns = ['error', 'exception', 'failed', 'failure', 'fatal', 'critical']
        if any(pattern in message_lower for pattern in generic_error_patterns):
            return 'generic_error'
        
        return 'unknown'
    
    def _extract_error_type_from_structured_log(self, log_data: Dict[str, Any]) -> Optional[str]:
        """Extract error type from structured log data"""
        # Check exception fields
        exception_message = (log_data.get('attributes', {}).get('exception.message') or 
                           log_data.get('exception', {}).get('message', ''))
        
        if exception_message:
            return self._extract_error_type(exception_message)
        
        # Check exception type
        exception_type = (log_data.get('attributes', {}).get('exception.type') or 
                         log_data.get('exception', {}).get('type', ''))
        
        if exception_type:
            exception_type_lower = exception_type.lower()
            if 'throttl' in exception_type_lower or 'rate' in exception_type_lower:
                return 'rate_limit'
            elif 'timeout' in exception_type_lower:
                return 'timeout'
            elif 'auth' in exception_type_lower or 'forbidden' in exception_type_lower:
                return 'authentication'
        
        return None
    
    def get_available_log_groups(self) -> List[str]:
        """Get list of available log groups"""
        try:
            all_groups = []
            paginator = self.client.get_paginator('describe_log_groups')
            
            for page in paginator.paginate():
                for log_group in page.get('logGroups', []):
                    all_groups.append(log_group['logGroupName'])
            
            return all_groups
        except ClientError as e:
            logger.error(f"Error fetching log groups: {e}")
            return []
    
    def get_agent_related_log_groups(self) -> List[str]:
        """Get log groups that are likely related to agents"""
        all_groups = self.get_available_log_groups()
        agent_groups = []
        
        agent_keywords = [
            'bedrock-agentcore',
            'bedrock/agent', 
            'agentcore',
            'strands',
            'agent',
            'spans'
        ]
        
        for group in all_groups:
            if any(keyword in group.lower() for keyword in agent_keywords):
                agent_groups.append(group)
        
        return agent_groups
    
    def test_connection(self) -> bool:
        """Test CloudWatch connection"""
        try:
            self.client.describe_log_groups(limit=1)
            return True
        except ClientError:
            return False
    
    def test_metrics_access(self) -> Dict[str, bool]:
        """Test access to different CloudWatch metrics namespaces"""
        cloudwatch_metrics = boto3.client('cloudwatch', region_name=self.region)
        
        test_results = {}
        namespaces_to_test = [
            'AWS/Bedrock/Agents',
            'bedrock-agentcore', 
            'AWS/Lambda'
        ]
        
        for namespace in namespaces_to_test:
            try:
                # Try to list metrics in this namespace
                response = cloudwatch_metrics.list_metrics(
                    Namespace=namespace
                )
                test_results[namespace] = True
            except ClientError:
                test_results[namespace] = False
        
        return test_results