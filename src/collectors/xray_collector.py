"""
X-Ray Traces Collector for AgentCore Debugger Assistant
"""
import boto3
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class XRayCollector:
    """Collects and processes traces from AWS X-Ray"""
    
    def __init__(self, region: str = 'us-east-1'):
        """Initialize X-Ray collector
        
        Args:
            region: AWS region for X-Ray client
        """
        self.region = region
        self.client = boto3.client('xray', region_name=region)
    
    def fetch_traces(self, start_time: datetime, end_time: datetime, 
                    filter_expression: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch traces from X-Ray with error filtering
        
        Args:
            start_time: Start time for trace search
            end_time: End time for trace search
            filter_expression: X-Ray filter expression
            
        Returns:
            List of trace summaries
        """
        try:
            # Default filter for errors and faults
            default_filter = 'error = true OR fault = true OR responsetime > 5'
            filter_expr = filter_expression or default_filter
            
            response = self.client.get_trace_summaries(
                TimeRangeType='TimeRangeByStartTime',
                StartTime=start_time,
                EndTime=end_time,
                FilterExpression=filter_expr
            )
            
            traces = response.get('TraceSummaries', [])
            
            # Handle pagination
            while response.get('NextToken'):
                response = self.client.get_trace_summaries(
                    TimeRangeType='TimeRangeByStartTime',
                    StartTime=start_time,
                    EndTime=end_time,
                    FilterExpression=filter_expr,
                    NextToken=response['NextToken']
                )
                traces.extend(response.get('TraceSummaries', []))
            
            return traces
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidRequestException':
                logger.warning("X-Ray service not available or no traces found")
                return []
            else:
                logger.error(f"Error fetching X-Ray traces: {e}")
                return []
    
    def get_trace_details(self, trace_ids: List[str]) -> List[Dict[str, Any]]:
        """Get detailed trace information
        
        Args:
            trace_ids: List of trace IDs to fetch details for
            
        Returns:
            List of detailed trace data
        """
        traces = []
        
        # X-Ray batch_get_traces has a limit of 5 trace IDs per request
        batch_size = 5
        for i in range(0, len(trace_ids), batch_size):
            batch_ids = trace_ids[i:i + batch_size]
            
            try:
                response = self.client.batch_get_traces(TraceIds=batch_ids)
                traces.extend(response.get('Traces', []))
            except ClientError as e:
                logger.warning(f"Could not fetch traces {batch_ids}: {e}")
                continue
        
        return traces
    
    def extract_error_spans(self, trace_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract spans with errors from trace data
        
        Args:
            trace_data: Detailed trace data from X-Ray
            
        Returns:
            List of error spans with context
        """
        error_spans = []
        
        for trace in trace_data:
            trace_id = trace.get('Id')
            
            for segment in trace.get('Segments', []):
                try:
                    segment_doc = json.loads(segment.get('Document', '{}'))
                    
                    # Check if segment has error or fault
                    if segment_doc.get('error') or segment_doc.get('fault'):
                        error_span = {
                            'trace_id': trace_id,
                            'segment_id': segment_doc.get('id'),
                            'name': segment_doc.get('name', 'Unknown'),
                            'start_time': segment_doc.get('start_time'),
                            'end_time': segment_doc.get('end_time'),
                            'duration': self._calculate_duration(
                                segment_doc.get('start_time'),
                                segment_doc.get('end_time')
                            ),
                            'error': segment_doc.get('error', False),
                            'fault': segment_doc.get('fault', False),
                            'cause': segment_doc.get('cause'),
                            'annotations': segment_doc.get('annotations', {}),
                            'metadata': segment_doc.get('metadata', {}),
                            'service_name': segment_doc.get('name'),
                            'http_status': self._extract_http_status(segment_doc),
                            'error_message': self._extract_error_message(segment_doc),
                            'exception_type': self._extract_exception_type(segment_doc)
                        }
                        
                        error_spans.append(error_span)
                    
                    # Check subsegments for errors
                    subsegments = segment_doc.get('subsegments', [])
                    for subsegment in subsegments:
                        if subsegment.get('error') or subsegment.get('fault'):
                            error_span = {
                                'trace_id': trace_id,
                                'segment_id': subsegment.get('id'),
                                'parent_id': segment_doc.get('id'),
                                'name': subsegment.get('name', 'Unknown'),
                                'start_time': subsegment.get('start_time'),
                                'end_time': subsegment.get('end_time'),
                                'duration': self._calculate_duration(
                                    subsegment.get('start_time'),
                                    subsegment.get('end_time')
                                ),
                                'error': subsegment.get('error', False),
                                'fault': subsegment.get('fault', False),
                                'cause': subsegment.get('cause'),
                                'annotations': subsegment.get('annotations', {}),
                                'metadata': subsegment.get('metadata', {}),
                                'service_name': segment_doc.get('name'),
                                'subsegment_name': subsegment.get('name'),
                                'http_status': self._extract_http_status(subsegment),
                                'error_message': self._extract_error_message(subsegment),
                                'exception_type': self._extract_exception_type(subsegment)
                            }
                            
                            error_spans.append(error_span)
                
                except json.JSONDecodeError as e:
                    logger.warning(f"Could not parse segment document: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing segment: {e}")
                    continue
        
        return error_spans
    
    def _calculate_duration(self, start_time: Optional[float], 
                          end_time: Optional[float]) -> Optional[float]:
        """Calculate duration in seconds"""
        if start_time and end_time:
            return end_time - start_time
        return None
    
    def _extract_http_status(self, segment_doc: Dict[str, Any]) -> Optional[int]:
        """Extract HTTP status code from segment"""
        http_info = segment_doc.get('http', {})
        response_info = http_info.get('response', {})
        return response_info.get('status')
    
    def _extract_error_message(self, segment_doc: Dict[str, Any]) -> Optional[str]:
        """Extract error message from segment"""
        cause = segment_doc.get('cause')
        if cause:
            if isinstance(cause, dict):
                return cause.get('message')
            elif isinstance(cause, str):
                return cause
        
        # Check in exceptions
        exceptions = segment_doc.get('exceptions', [])
        if exceptions and len(exceptions) > 0:
            return exceptions[0].get('message')
        
        return None
    
    def _extract_exception_type(self, segment_doc: Dict[str, Any]) -> Optional[str]:
        """Extract exception type from segment"""
        exceptions = segment_doc.get('exceptions', [])
        if exceptions and len(exceptions) > 0:
            return exceptions[0].get('type')
        
        cause = segment_doc.get('cause')
        if isinstance(cause, dict):
            return cause.get('type')
        
        return None
    
    def get_service_map(self, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get X-Ray service map for the time range
        
        Args:
            start_time: Start time for service map
            end_time: End time for service map
            
        Returns:
            Service map data
        """
        try:
            response = self.client.get_service_graph(
                StartTime=start_time,
                EndTime=end_time
            )
            return response
        except ClientError as e:
            logger.error(f"Error fetching service map: {e}")
            return {}
    
    def analyze_trace_performance(self, trace_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze trace performance metrics
        
        Args:
            trace_data: Detailed trace data
            
        Returns:
            Performance analysis results
        """
        if not trace_data:
            return {}
        
        durations = []
        error_count = 0
        fault_count = 0
        service_durations = {}
        
        for trace in trace_data:
            for segment in trace.get('Segments', []):
                try:
                    segment_doc = json.loads(segment.get('Document', '{}'))
                    
                    # Calculate duration
                    start_time = segment_doc.get('start_time')
                    end_time = segment_doc.get('end_time')
                    if start_time and end_time:
                        duration = end_time - start_time
                        durations.append(duration)
                        
                        # Track service-specific durations
                        service_name = segment_doc.get('name', 'Unknown')
                        if service_name not in service_durations:
                            service_durations[service_name] = []
                        service_durations[service_name].append(duration)
                    
                    # Count errors and faults
                    if segment_doc.get('error'):
                        error_count += 1
                    if segment_doc.get('fault'):
                        fault_count += 1
                
                except json.JSONDecodeError:
                    continue
        
        # Calculate statistics
        analysis = {
            'total_traces': len(trace_data),
            'total_segments': sum(len(trace.get('Segments', [])) for trace in trace_data),
            'error_count': error_count,
            'fault_count': fault_count,
            'avg_duration': sum(durations) / len(durations) if durations else 0,
            'min_duration': min(durations) if durations else 0,
            'max_duration': max(durations) if durations else 0,
            'service_performance': {}
        }
        
        # Calculate per-service statistics
        for service, service_durs in service_durations.items():
            analysis['service_performance'][service] = {
                'avg_duration': sum(service_durs) / len(service_durs),
                'min_duration': min(service_durs),
                'max_duration': max(service_durs),
                'request_count': len(service_durs)
            }
        
        return analysis
    
    def test_connection(self) -> bool:
        """Test X-Ray connection"""
        try:
            # Try to get service graph for a small time window
            from datetime import timedelta
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=1)
            self.client.get_service_graph(StartTime=start_time, EndTime=end_time)
            return True
        except Exception as e:
            # Log the error for debugging but don't fail
            print(f"X-Ray connection test failed: {e}")
            return False