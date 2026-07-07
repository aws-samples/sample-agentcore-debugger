"""
Metrics Collector for AgentCore Observability
Collects metrics from CloudWatch, X-Ray, and AgentCore APIs
"""
import os
import boto3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from botocore.exceptions import ClientError

def to_timestamp_ms(dt):
    """Convert datetime to millisecond timestamp, treating naive datetimes as UTC"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class MetricsCollector:
    """Collect observability metrics for AgentCore agents"""
    
    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        from src.core.retry_config import ADAPTIVE_RETRY
        self.cloudwatch = boto3.client('cloudwatch', region_name=region, config=ADAPTIVE_RETRY)
        self.logs = boto3.client('logs', region_name=region, config=ADAPTIVE_RETRY)
        self.agentcore = boto3.client('bedrock-agentcore', region_name=region, config=ADAPTIVE_RETRY)
        self.agentcore_control = boto3.client('bedrock-agentcore-control', region_name=region, config=ADAPTIVE_RETRY)
        
        # Try to use CloudWatch Observability Access Manager if available
        try:
            self.oam = boto3.client('oam', region_name=region)
        except:
            self.oam = None
    
    def get_agent_metrics(self, agent_runtime_id: str, hours: int = 24, start_time: datetime = None, end_time: datetime = None) -> Dict[str, Any]:
        """Get comprehensive metrics for an agent
        
        Args:
            agent_runtime_id: AgentCore Runtime ID or ARN
            hours: Number of hours to look back (if start_time/end_time not provided)
            start_time: Optional start time for metrics
            end_time: Optional end time for metrics
            
        Returns:
            Dictionary with all metrics
        """
        # Extract runtime ID from ARN if needed
        if agent_runtime_id.startswith('arn:'):
            # Extract the runtime ID from ARN: arn:aws:bedrock-agentcore:region:account:runtime/ID
            runtime_id = agent_runtime_id.split('/')[-1]
        else:
            runtime_id = agent_runtime_id
        
        # Use provided times or calculate from hours
        # Make sure we use timezone-aware datetimes
        if not end_time:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        if not start_time:
            start_time = end_time - timedelta(hours=hours)
        
        # Get log group name for this agent
        log_group = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
        
        # Get comprehensive metrics from CloudWatch Metrics (primary source - most reliable and persistent)
        print(f"Querying CloudWatch Metrics for: {runtime_id}")
        print(f"Time range: {start_time} to {end_time}")
        cw_metrics = self._get_cloudwatch_metrics(runtime_id, agent_runtime_id, start_time, end_time)
        
        # Get recent invocation logs
        recent_invocations = self._get_recent_runtime_logs(log_group, limit=10)
        
        # Use CloudWatch Metrics as primary source
        primary_metrics = cw_metrics
        data_source = 'cloudwatch_metrics' if cw_metrics.get('invocations', 0) > 0 else 'none'
        
        metrics = {
            'agent_runtime_id': runtime_id,
            'agent_runtime_arn': agent_runtime_id if agent_runtime_id.startswith('arn:') else None,
            'log_group': log_group,
            'service_name': f"{runtime_id.split('-')[0]}.DEFAULT",
            'data_source': data_source,
            'time_range': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat(),
                'hours': hours
            },
            # Runtime metrics (AWS Console format) from CloudWatch Logs
            'runtime_sessions': primary_metrics.get('sessions', 0),
            'runtime_invocations': primary_metrics.get('invocations', 0),
            'runtime_errors': primary_metrics.get('errors', 0),
            'runtime_faults': primary_metrics.get('faults', 0),
            'runtime_throttles': primary_metrics.get('throttles', 0),
            'runtime_error_rate': primary_metrics.get('error_rate', 0),
            'runtime_throttle_rate': primary_metrics.get('throttle_rate', 0),
            # Performance metrics
            'avg_duration_seconds': primary_metrics.get('avg_duration', 0),
            'max_duration_seconds': primary_metrics.get('max_duration', 0),
            'min_duration_seconds': primary_metrics.get('min_duration', 0),
            # Resource consumption
            'vcpu_consumption_hours': primary_metrics.get('vcpu_hours', 0),
            'memory_consumption_gb_hours': primary_metrics.get('memory_gb_hours', 0),
            # Recent logs
            'recent_invocations': recent_invocations
        }
        
        return metrics
    
    def _get_invocation_metrics(self, agent_runtime_id: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get invocation count and success rate"""
        try:
            # Query CloudWatch metrics for invocations
            response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/BedrockAgentCore',
                MetricName='Invocations',
                Dimensions=[
                    {'Name': 'AgentRuntimeId', 'Value': agent_runtime_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600,  # 1 hour
                Statistics=['Sum', 'SampleCount']
            )
            
            total_invocations = sum(dp['Sum'] for dp in response.get('Datapoints', []))
            
            # Get error count
            error_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/BedrockAgentCore',
                MetricName='Errors',
                Dimensions=[
                    {'Name': 'AgentRuntimeId', 'Value': agent_runtime_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600,
                Statistics=['Sum']
            )
            
            total_errors = sum(dp['Sum'] for dp in error_response.get('Datapoints', []))
            success_rate = ((total_invocations - total_errors) / total_invocations * 100) if total_invocations > 0 else 0
            
            return {
                'total': int(total_invocations),
                'errors': int(total_errors),
                'success_rate': round(success_rate, 2),
                'datapoints': response.get('Datapoints', [])
            }
            
        except ClientError as e:
            return {'total': 0, 'errors': 0, 'success_rate': 0, 'error': str(e)}
    
    def _get_error_metrics(self, agent_runtime_id: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get detailed error metrics"""
        try:
            # Get error rate over time
            response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/BedrockAgentCore',
                MetricName='Errors',
                Dimensions=[
                    {'Name': 'AgentRuntimeId', 'Value': agent_runtime_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600,
                Statistics=['Sum', 'Average']
            )
            
            datapoints = response.get('Datapoints', [])
            total_errors = sum(dp['Sum'] for dp in datapoints)
            avg_error_rate = sum(dp['Average'] for dp in datapoints) / len(datapoints) if datapoints else 0
            
            return {
                'total_errors': int(total_errors),
                'average_error_rate': round(avg_error_rate, 4),
                'datapoints': sorted(datapoints, key=lambda x: x['Timestamp'])
            }
            
        except ClientError as e:
            return {'total_errors': 0, 'average_error_rate': 0, 'error': str(e)}
    
    def _get_performance_metrics(self, agent_runtime_id: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get performance metrics (latency, duration)"""
        try:
            # Get invocation duration
            response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/BedrockAgentCore',
                MetricName='Duration',
                Dimensions=[
                    {'Name': 'AgentRuntimeId', 'Value': agent_runtime_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600,
                Statistics=['Average', 'Maximum', 'Minimum']
            )
            
            datapoints = response.get('Datapoints', [])
            
            if datapoints:
                avg_duration = sum(dp['Average'] for dp in datapoints) / len(datapoints)
                max_duration = max(dp['Maximum'] for dp in datapoints)
                min_duration = min(dp['Minimum'] for dp in datapoints)
            else:
                avg_duration = max_duration = min_duration = 0
            
            return {
                'average_duration_ms': round(avg_duration, 2),
                'max_duration_ms': round(max_duration, 2),
                'min_duration_ms': round(min_duration, 2),
                'datapoints': sorted(datapoints, key=lambda x: x['Timestamp'])
            }
            
        except ClientError as e:
            return {'average_duration_ms': 0, 'max_duration_ms': 0, 'min_duration_ms': 0, 'error': str(e)}
    
    def _get_trace_summary(self, agent_runtime_id: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get X-Ray trace summary - DISABLED"""
        # X-Ray has been disabled - returning empty metrics
        return {
            'total_traces': 0,
            'error_traces': 0,
            'fault_traces': 0,
            'success_rate': 0,
            'avg_response_time': 0,
            'max_response_time': 0,
            'min_response_time': 0
        }
    
    def _get_throttle_metrics(self, agent_runtime_id: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get throttling metrics"""
        try:
            response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/BedrockAgentCore',
                MetricName='Throttles',
                Dimensions=[
                    {'Name': 'AgentRuntimeId', 'Value': agent_runtime_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=3600,
                Statistics=['Sum']
            )
            
            datapoints = response.get('Datapoints', [])
            total_throttles = sum(dp['Sum'] for dp in datapoints)
            
            return {
                'total_throttles': int(total_throttles),
                'datapoints': sorted(datapoints, key=lambda x: x['Timestamp'])
            }
            
        except ClientError as e:
            return {'total_throttles': 0, 'error': str(e)}
    
    def _get_invocation_metrics_from_logs(self, log_group: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get invocation metrics from CloudWatch Logs"""
        try:
            # Convert to milliseconds timestamp
            start_ms = to_timestamp_ms(start_time)
            end_ms = to_timestamp_ms(end_time)
            
            # Query for successful invocations
            success_query = f"""
            fields @timestamp, @message
            | filter @message like /Invocation completed successfully/
            | stats count() as invocations
            """
            
            success_response = self.logs.start_query(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                queryString=success_query
            )
            
            query_id = success_response['queryId']
            
            # Wait for query to complete
            import time
            for _ in range(10):  # Max 10 seconds
                result = self.logs.get_query_results(queryId=query_id)
                if result['status'] == 'Complete':
                    break
                time.sleep(1)
            
            total_invocations = 0
            if result['status'] == 'Complete' and result['results']:
                for row in result['results']:
                    for field in row:
                        if field['field'] == 'invocations':
                            total_invocations = int(field['value'])
            
            # Query for errors
            error_query = f"""
            fields @timestamp, @message
            | filter @message like /error/ or @message like /Error/ or @message like /ERROR/ or @message like /failed/
            | stats count() as errors
            """
            
            error_response = self.logs.start_query(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                queryString=error_query
            )
            
            error_query_id = error_response['queryId']
            
            # Wait for error query
            for _ in range(10):
                error_result = self.logs.get_query_results(queryId=error_query_id)
                if error_result['status'] == 'Complete':
                    break
                time.sleep(1)
            
            total_errors = 0
            if error_result['status'] == 'Complete' and error_result['results']:
                for row in error_result['results']:
                    for field in row:
                        if field['field'] == 'errors':
                            total_errors = int(field['value'])
            
            success_rate = ((total_invocations - total_errors) / total_invocations * 100) if total_invocations > 0 else 0
            
            return {
                'total': total_invocations,
                'errors': total_errors,
                'success_rate': round(success_rate, 2)
            }
            
        except Exception as e:
            return {'total': 0, 'errors': 0, 'success_rate': 0, 'error': str(e)}
    
    def _get_error_metrics_from_logs(self, log_group: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get error metrics from CloudWatch Logs"""
        try:
            start_ms = to_timestamp_ms(start_time)
            end_ms = to_timestamp_ms(end_time)
            
            # Query for error details
            error_query = f"""
            fields @timestamp, @message
            | filter @message like /error/ or @message like /Error/ or @message like /ERROR/ or @message like /exception/ or @message like /failed/
            | stats count() as error_count by bin(5m) as time_bucket
            """
            
            response = self.logs.start_query(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                queryString=error_query
            )
            
            query_id = response['queryId']
            
            # Wait for query
            import time
            for _ in range(10):
                result = self.logs.get_query_results(queryId=query_id)
                if result['status'] == 'Complete':
                    break
                time.sleep(1)
            
            total_errors = 0
            datapoints = []
            
            if result['status'] == 'Complete' and result['results']:
                for row in result['results']:
                    error_count = 0
                    timestamp = None
                    
                    for field in row:
                        if field['field'] == 'error_count':
                            error_count = int(field['value'])
                            total_errors += error_count
                        elif field['field'] == 'time_bucket':
                            timestamp = field['value']
                    
                    if timestamp:
                        datapoints.append({
                            'Timestamp': timestamp,
                            'Sum': error_count
                        })
            
            return {
                'total_errors': total_errors,
                'average_error_rate': 0,  # Can calculate if needed
                'datapoints': datapoints
            }
            
        except Exception as e:
            return {'total_errors': 0, 'average_error_rate': 0, 'error': str(e)}
    
    def _get_performance_metrics_from_logs(self, log_group: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get performance metrics from CloudWatch Logs"""
        try:
            start_ms = to_timestamp_ms(start_time)
            end_ms = to_timestamp_ms(end_time)
            
            # Query for duration/latency info
            perf_query = f"""
            fields @timestamp, @message
            | filter @message like /duration/ or @message like /latency/ or @message like /completed/
            | stats count() as invocations, avg(@duration) as avg_duration
            """
            
            response = self.logs.start_query(
                logGroupName=log_group,
                startTime=start_ms,
                endTime=end_ms,
                queryString=perf_query
            )
            
            query_id = response['queryId']
            
            # Wait for query
            import time
            for _ in range(10):
                result = self.logs.get_query_results(queryId=query_id)
                if result['status'] == 'Complete':
                    break
                time.sleep(1)
            
            avg_duration = 0
            
            if result['status'] == 'Complete' and result['results']:
                for row in result['results']:
                    for field in row:
                        if field['field'] == 'avg_duration' and field['value']:
                            try:
                                avg_duration = float(field['value'])
                            except:
                                pass
            
            return {
                'average_duration_ms': round(avg_duration, 2),
                'max_duration_ms': 0,  # Would need more complex query
                'min_duration_ms': 0,
                'datapoints': []
            }
            
        except Exception as e:
            return {'average_duration_ms': 0, 'max_duration_ms': 0, 'min_duration_ms': 0, 'error': str(e)}
    
    def _get_recent_invocations(self, log_group: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent invocation logs (deprecated - use _get_recent_runtime_logs)"""
        return self._get_recent_runtime_logs(log_group, limit)
    
    def _get_recent_runtime_logs(self, log_group: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent runtime invocation logs in structured format"""
        try:
            import json
            
            # Get recent log streams (runtime-logs streams contain invocation completion messages)
            streams_response = self.logs.describe_log_streams(
                logGroupName=log_group,
                orderBy='LastEventTime',
                descending=True,
                limit=10
            )
            
            streams = streams_response.get('logStreams', [])
            
            if not streams:
                return []
            
            invocations = []
            
            # Get events from runtime-logs streams
            for stream in streams:
                if '[runtime-logs]' in stream['logStreamName']:
                    try:
                        events_response = self.logs.get_log_events(
                            logGroupName=log_group,
                            logStreamName=stream['logStreamName'],
                            limit=5,
                            startFromHead=False
                        )
                        
                        for event in events_response.get('events', []):
                            try:
                                log_data = json.loads(event['message'])
                                invocations.append({
                                    'timestamp': log_data.get('timestamp', 'N/A'),
                                    'level': log_data.get('level', 'INFO'),
                                    'message': log_data.get('message', 'N/A'),
                                    'session_id': log_data.get('sessionId', 'N/A'),
                                    'request_id': log_data.get('requestId', 'N/A')
                                })
                            except json.JSONDecodeError:
                                pass
                    except Exception:
                        pass
                
                if len(invocations) >= limit:
                    break
            
            return invocations[:limit]
            
        except Exception as e:
            return []
    
    def _get_metrics_from_logs(self, log_group: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get comprehensive metrics from CloudWatch Logs using Insights queries"""
        try:
            # Use epoch time in seconds (not milliseconds) for CloudWatch Insights
            start_epoch = int(start_time.timestamp())
            end_epoch = int(end_time.timestamp())
            
            # Simple query to count invocations
            query = """
            fields @timestamp, @message
            | filter @message like /Invocation completed successfully/
            | stats count() as total_invocations
            """
            
            response = self.logs.start_query(
                logGroupName=log_group,
                startTime=start_epoch,
                endTime=end_epoch,
                queryString=query
            )
            
            query_id = response['queryId']
            
            # Wait for query to complete
            import time
            for _ in range(15):  # Max 15 seconds
                result = self.logs.get_query_results(queryId=query_id)
                if result['status'] == 'Complete':
                    break
                time.sleep(1)
            
            metrics = {
                'invocations': 0,
                'sessions': 0,
                'errors': 0,
                'error_rate': 0,
                'throttles': 0,
                'throttle_rate': 0,
                'avg_duration_ms': 0,
                'timeline': []
            }
            
            if result['status'] == 'Complete' and result['results']:
                for row in result['results']:
                    for field in row:
                        field_name = field['field']
                        field_value = field['value']
                        
                        if field_name == 'total_invocations':
                            metrics['invocations'] = int(float(field_value))
                        elif field_name == 'unique_sessions':
                            metrics['sessions'] = int(float(field_value))
                        elif field_name == 'total_errors':
                            metrics['errors'] = int(float(field_value))
                        elif field_name == 'total_throttles':
                            metrics['throttles'] = int(float(field_value))
                        elif field_name == 'avg_duration':
                            try:
                                metrics['avg_duration_ms'] = float(field_value)
                            except:
                                pass
                
                # Calculate rates
                if metrics['invocations'] > 0:
                    metrics['error_rate'] = round((metrics['errors'] / metrics['invocations']) * 100, 2)
                    metrics['throttle_rate'] = round((metrics['throttles'] / metrics['invocations']) * 100, 2)
            
            # Get timeline data
            timeline_query = """
            fields @timestamp, @message
            | parse @message '{"timestamp": "*", "level": "*", "message": "*"*' as ts, level, msg
            | filter msg like /Invocation completed/
            | stats count() as invocations by bin(5m) as time_bucket
            | sort time_bucket asc
            """
            
            timeline_response = self.logs.start_query(
                logGroupName=log_group,
                startTime=start_epoch,
                endTime=end_epoch,
                queryString=timeline_query
            )
            
            timeline_query_id = timeline_response['queryId']
            
            for _ in range(10):
                timeline_result = self.logs.get_query_results(queryId=timeline_query_id)
                if timeline_result['status'] == 'Complete':
                    break
                time.sleep(1)
            
            if timeline_result['status'] == 'Complete' and timeline_result['results']:
                timeline = []
                for row in timeline_result['results']:
                    timestamp = None
                    count = 0
                    
                    for field in row:
                        if field['field'] == 'time_bucket':
                            timestamp = field['value']
                        elif field['field'] == 'invocations':
                            count = int(float(field['value']))
                    
                    if timestamp:
                        timeline.append({
                            'timestamp': timestamp,
                            'invocations': count
                        })
                
                metrics['timeline'] = timeline
            
            return metrics
            
        except Exception as e:
            return {
                'invocations': 0,
                'sessions': 0,
                'errors': 0,
                'error_rate': 0,
                'throttles': 0,
                'throttle_rate': 0,
                'avg_duration_ms': 0,
                'timeline': [],
                'error': str(e)
            }
    
    def _get_cloudwatch_metrics(self, runtime_id: str, agent_runtime_id: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get comprehensive metrics from CloudWatch Metrics (primary source - most reliable)"""
        try:
            # Build the ARN if not provided
            if agent_runtime_id.startswith('arn:'):
                resource_arn = agent_runtime_id
            else:
                # Construct ARN from runtime ID using STS to get account ID
                import boto3
                sts = boto3.client('sts')
                account_id = sts.get_caller_identity()['Account']
                region = os.getenv('AWS_REGION', 'us-east-1')
                resource_arn = f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{runtime_id}"
            
            # Agent name for the Name dimension
            agent_name = runtime_id.split('-')[0]
            
            print(f"Querying AWS/Bedrock-AgentCore namespace")
            print(f"   Resource: {resource_arn}")
            print(f"   Name: {agent_name}::DEFAULT")
            
            # Common dimensions for agent runtime metrics
            dimensions = [
                {'Name': 'Resource', 'Value': resource_arn},
                {'Name': 'Operation', 'Value': 'InvokeAgentRuntime'},
                {'Name': 'Name', 'Value': f'{agent_name}::DEFAULT'}
            ]
            
            # Calculate appropriate period based on time range
            # CloudWatch limit: max 1440 datapoints per request
            time_range_seconds = (end_time - start_time).total_seconds()
            
            # Calculate minimum period needed to stay under 1440 datapoints
            min_period = int(time_range_seconds / 1440) + 1
            
            # Round up to valid CloudWatch period (60, 300, 3600, etc.)
            if min_period <= 60:
                period = 60  # 1 minute
            elif min_period <= 300:
                period = 300  # 5 minutes
            elif min_period <= 3600:
                period = 3600  # 1 hour
            else:
                period = 86400  # 1 day
            
            print(f"   Period: {period}s ({period//60} minutes)" if period < 3600 else f"   Period: {period}s ({period//3600} hours)")
            
            # Get Invocations
            invocations_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='Invocations',
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Sum']
            )
            
            total_invocations = sum(dp['Sum'] for dp in invocations_response.get('Datapoints', []))
            
            # Get Sessions
            sessions_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='Sessions',
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Sum']
            )
            
            total_sessions = sum(dp['Sum'] for dp in sessions_response.get('Datapoints', []))
            
            # Get Errors (System + User)
            system_errors_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='SystemErrors',
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Sum']
            )
            
            user_errors_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='UserErrors',
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Sum']
            )
            
            system_errors = sum(dp['Sum'] for dp in system_errors_response.get('Datapoints', []))
            user_errors = sum(dp['Sum'] for dp in user_errors_response.get('Datapoints', []))
            total_errors = system_errors + user_errors
            
            # Get Throttles
            throttles_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='Throttles',
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Sum']
            )
            
            total_throttles = sum(dp['Sum'] for dp in throttles_response.get('Datapoints', []))
            
            # Get Latency/Duration
            duration_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='Duration',
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Average', 'Maximum', 'Minimum']
            )
            
            duration_datapoints = duration_response.get('Datapoints', [])
            if duration_datapoints:
                avg_duration = sum(dp['Average'] for dp in duration_datapoints) / len(duration_datapoints)
                max_duration = max(dp['Maximum'] for dp in duration_datapoints)
                min_duration = min(dp['Minimum'] for dp in duration_datapoints)
            else:
                avg_duration = max_duration = min_duration = 0
            
            # Get CPU and Memory usage
            cpu_dimensions = [
                {'Name': 'Resource', 'Value': resource_arn},
                {'Name': 'Service', 'Value': 'AgentCore.Runtime'},
                {'Name': 'Name', 'Value': f'{agent_name}::DEFAULT'}
            ]
            
            cpu_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='CPUUsed-vCPUHours',
                Dimensions=cpu_dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Sum']
            )
            
            memory_response = self.cloudwatch.get_metric_statistics(
                Namespace='AWS/Bedrock-AgentCore',
                MetricName='MemoryUsed-GBHours',
                Dimensions=cpu_dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=['Sum']
            )
            
            vcpu_hours = sum(dp['Sum'] for dp in cpu_response.get('Datapoints', []))
            memory_gb_hours = sum(dp['Sum'] for dp in memory_response.get('Datapoints', []))
            
            print(f"Found {int(total_invocations)} invocations, {int(total_sessions)} sessions, {int(total_errors)} errors")
            
            # Calculate metrics
            error_rate = (total_errors / total_invocations * 100) if total_invocations > 0 else 0
            throttle_rate = (total_throttles / total_invocations * 100) if total_invocations > 0 else 0
            
            # Convert milliseconds to seconds for duration
            avg_duration_sec = avg_duration / 1000 if avg_duration > 0 else 0
            max_duration_sec = max_duration / 1000 if max_duration > 0 else 0
            min_duration_sec = min_duration / 1000 if min_duration > 0 else 0
            
            return {
                'invocations': int(total_invocations),
                'sessions': int(total_sessions),
                'errors': int(total_errors),
                'faults': int(system_errors),
                'throttles': int(total_throttles),
                'error_rate': round(error_rate, 2),
                'throttle_rate': round(throttle_rate, 2),
                'avg_duration': round(avg_duration_sec, 3),
                'max_duration': round(max_duration_sec, 3),
                'min_duration': round(min_duration_sec, 3),
                'vcpu_hours': round(vcpu_hours, 3),
                'memory_gb_hours': round(memory_gb_hours, 1)
            }
            
        except Exception as e:
            print(f"Error getting CloudWatch Metrics: {e}")
            import traceback
            traceback.print_exc()
            return {
                'invocations': 0,
                'sessions': 0,
                'errors': 0,
                'faults': 0,
                'throttles': 0,
                'error_rate': 0,
                'throttle_rate': 0,
                'avg_duration': 0,
                'max_duration': 0,
                'min_duration': 0,
                'vcpu_hours': 0,
                'memory_gb_hours': 0
            }
    
    def _get_comprehensive_metrics_from_logs(self, log_group: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get comprehensive metrics from CloudWatch Logs (primary source - persists longer)"""
        try:
            import json
            import re
            
            # Get all runtime log streams
            streams_response = self.logs.describe_log_streams(
                logGroupName=log_group,
                orderBy='LastEventTime',
                descending=True,
                limit=20
            )
            
            streams = streams_response.get('logStreams', [])
            print(f"Found {len(streams)} log streams")
            
            invocations = []
            sessions = set()
            errors = 0
            durations = []
            
            # Process each runtime-logs stream
            for stream in streams:
                if '[runtime-logs]' in stream['logStreamName']:
                    try:
                        # Get events in time range
                        events_response = self.logs.get_log_events(
                            logGroupName=log_group,
                            logStreamName=stream['logStreamName'],
                            startTime=to_timestamp_ms(start_time),
                            endTime=to_timestamp_ms(end_time),
                            limit=100
                        )
                        
                        for event in events_response.get('events', []):
                            try:
                                log_data = json.loads(event['message'])
                                message = log_data.get('message', '')
                                level = log_data.get('level', 'INFO')
                                session_id = log_data.get('sessionId')
                                
                                # Count invocations
                                if 'Invocation completed successfully' in message:
                                    invocations.append(log_data)
                                    if session_id:
                                        sessions.add(session_id)
                                    
                                    # Extract duration from message
                                    duration_match = re.search(r'\((\d+\.\d+)s\)', message)
                                    if duration_match:
                                        duration = float(duration_match.group(1))
                                        durations.append(duration)
                                
                                # Count errors
                                elif level in ['ERROR', 'FATAL'] or 'error' in message.lower():
                                    errors += 1
                                    
                            except json.JSONDecodeError:
                                pass
                                
                    except Exception as e:
                        continue
            
            total_invocations = len(invocations)
            unique_sessions = len(sessions)
            
            print(f"Found {total_invocations} invocations, {unique_sessions} sessions, {errors} errors")
            
            # Calculate metrics
            error_rate = (errors / total_invocations * 100) if total_invocations > 0 else 0
            avg_duration = sum(durations) / len(durations) if durations else 0
            max_duration = max(durations) if durations else 0
            min_duration = min(durations) if durations else 0
            
            # Calculate resource consumption
            total_duration_hours = sum(durations) / 3600 if durations else 0
            vcpu_hours = total_duration_hours * 0.25  # Estimate 0.25 vCPU
            memory_gb_hours = total_duration_hours * 0.5  # Estimate 512MB
            
            return {
                'invocations': total_invocations,
                'sessions': unique_sessions,
                'errors': errors,
                'faults': 0,
                'throttles': 0,
                'error_rate': round(error_rate, 2),
                'throttle_rate': 0,
                'avg_duration': round(avg_duration, 3),
                'max_duration': round(max_duration, 3),
                'min_duration': round(min_duration, 3),
                'vcpu_hours': round(vcpu_hours, 3),
                'memory_gb_hours': round(memory_gb_hours, 1)
            }
            
        except Exception as e:
            print(f"Error getting metrics from logs: {e}")
            return {
                'invocations': 0,
                'sessions': 0,
                'errors': 0,
                'faults': 0,
                'throttles': 0,
                'error_rate': 0,
                'throttle_rate': 0,
                'avg_duration': 0,
                'max_duration': 0,
                'min_duration': 0,
                'vcpu_hours': 0,
                'memory_gb_hours': 0
            }
    
    def _get_xray_service_metrics(self, runtime_id: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get comprehensive metrics from X-Ray traces (ADOT instrumentation) - DISABLED"""
        # X-Ray has been disabled - returning empty metrics
        return {
            'invocations': 0,
            'sessions': 0,
            'errors': 0,
            'faults': 0,
            'throttles': 0,
            'error_rate': 0,
            'throttle_rate': 0,
            'avg_duration': 0,
            'max_duration': 0,
            'min_duration': 0,
            'vcpu_hours': 0,
            'memory_gb_hours': 0
        }
        
        # OLD CODE - X-Ray disabled
        """
        try:
            # Service name format: agent_name.DEFAULT
            service_name = f"{runtime_id.split('-')[0]}.DEFAULT"
            
            # Debug logging
            print(f"Querying X-Ray for service: {service_name}")
            print(f"Time range: {start_time} to {end_time}")
            
            # Get trace summaries for this service
            response = self.xray.get_trace_summaries(
                StartTime=start_time,
                EndTime=end_time,
                FilterExpression=f'service("{service_name}")'
            )
            
            traces = response.get('TraceSummaries', [])
            print(f"Found {len(traces)} traces for {service_name}")
            
            if not traces:
                return {
                    'invocations': 0,
                    'sessions': 0,
                    'errors': 0,
                    'faults': 0,
                    'throttles': 0,
                    'error_rate': 0,
                    'throttle_rate': 0,
                    'avg_duration': 0,
                    'max_duration': 0,
                    'min_duration': 0,
                    'vcpu_hours': 0,
                    'memory_gb_hours': 0
                }
            
            # Calculate metrics from traces
            total_traces = len(traces)
            error_traces = sum(1 for t in traces if t.get('HasError'))
            fault_traces = sum(1 for t in traces if t.get('HasFault'))
            throttle_traces = sum(1 for t in traces if t.get('HasThrottle'))
            
            durations = [t.get('Duration', 0) for t in traces]
            
            # Get unique sessions from trace details (sample first 20)
            sessions = set()
            for trace in traces[:20]:
                try:
                    trace_detail = self.xray.batch_get_traces(TraceIds=[trace['Id']])
                    if trace_detail.get('Traces'):
                        for t in trace_detail['Traces']:
                            for segment in t.get('Segments', []):
                                import json
                                seg_doc = json.loads(segment['Document'])
                                if 'metadata' in seg_doc and 'session.id' in seg_doc['metadata']:
                                    sessions.add(seg_doc['metadata']['session.id'])
                except:
                    pass
            
            # Calculate resource consumption
            total_duration_hours = sum(durations) / 3600
            vcpu_hours = total_duration_hours * 0.25  # Estimate 0.25 vCPU
            memory_gb_hours = total_duration_hours * 0.5  # Estimate 512MB
            
            return {
                'invocations': total_traces,
                'sessions': len(sessions) if sessions else total_traces,
                'errors': error_traces,
                'faults': fault_traces,
                'throttles': throttle_traces,
                'error_rate': round((error_traces / total_traces) * 100, 2) if total_traces > 0 else 0,
                'throttle_rate': round((throttle_traces / total_traces) * 100, 2) if total_traces > 0 else 0,
                'avg_duration': round(sum(durations) / len(durations), 3) if durations else 0,
                'max_duration': round(max(durations), 3) if durations else 0,
                'min_duration': round(min(durations), 3) if durations else 0,
                'vcpu_hours': round(vcpu_hours, 3),
                'memory_gb_hours': round(memory_gb_hours, 1)
            }
            
        except Exception as e:
            return {
                'invocations': 0,
                'sessions': 0,
                'errors': 0,
                'error_rate': 0,
                'vcpu_hours': 0,
                'memory_gb_hours': 0,
                'error': str(e)
            }
        """
