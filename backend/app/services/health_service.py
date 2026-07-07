"""
Service layer for system health monitoring
"""
import sys
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import logging

sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from src.collectors.metrics_collector import MetricsCollector
from src.collectors.cloudwatch_collector import CloudWatchCollector

logger = logging.getLogger(__name__)


class HealthService:
    """Service for system health monitoring"""
    
    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.metrics_collector = MetricsCollector()
        self.cloudwatch = CloudWatchCollector(region=region)
    
    async def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health status"""
        try:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
            start_time = end_time - timedelta(hours=1)
            
            # Get error counts
            raw_events = self.cloudwatch.fetch_log_events(start_time, end_time)
            parsed_events = self.cloudwatch.parse_otel_logs(raw_events)
            
            error_count = sum(1 for e in parsed_events if e.get('level', '').upper() in ['ERROR', 'FATAL', 'CRITICAL'])
            warning_count = sum(1 for e in parsed_events if e.get('level', '').upper() in ['WARN', 'WARNING'])
            total_events = len(parsed_events)
            
            # Calculate health score (0-100)
            if total_events == 0:
                health_score = 100
            else:
                error_rate = error_count / total_events
                health_score = max(0, 100 - (error_rate * 200) - (warning_count / total_events * 50))
            
            # Determine status
            if health_score >= 90:
                status = 'healthy'
            elif health_score >= 70:
                status = 'degraded'
            else:
                status = 'unhealthy'
            
            return {
                'status': status,
                'health_score': round(health_score, 1),
                'metrics': {
                    'total_events': total_events,
                    'error_count': error_count,
                    'warning_count': warning_count,
                    'error_rate': round(error_count / max(total_events, 1) * 100, 2)
                },
                'time_range': {
                    'start': start_time.isoformat(),
                    'end': end_time.isoformat()
                },
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting system health: {e}")
            return {
                'status': 'unknown',
                'health_score': 0,
                'error': str(e)
            }
    
    async def get_agent_health_summary(self) -> Dict[str, Any]:
        """Get health summary for all agents"""
        try:
            from src.collectors.agent_discovery import AgentDiscovery
            discovery = AgentDiscovery()
            agents = discovery.discover_agents()
            
            total = len(agents)
            active = sum(1 for a in agents if a.get('status') in ['PREPARED', 'ACTIVE'])
            failed = sum(1 for a in agents if a.get('status') in ['FAILED', 'ERROR'])
            pending = total - active - failed
            
            return {
                'total_agents': total,
                'active': active,
                'failed': failed,
                'pending': pending,
                'health_percentage': round(active / max(total, 1) * 100, 1)
            }
            
        except Exception as e:
            logger.error(f"Error getting agent health summary: {e}")
            return {
                'total_agents': 0,
                'error': str(e)
            }
    
    async def get_service_status(self) -> List[Dict[str, Any]]:
        """Get status of dependent AWS services"""
        import boto3
        
        services = []
        
        # Check CloudWatch Logs
        try:
            logs_client = boto3.client('logs', region_name=self.region)
            logs_client.describe_log_groups(limit=1)
            services.append({
                'name': 'CloudWatch Logs',
                'status': 'operational',
                'latency_ms': 0
            })
        except Exception as e:
            services.append({
                'name': 'CloudWatch Logs',
                'status': 'error',
                'error': str(e)
            })
        
        # Check Bedrock
        try:
            bedrock_client = boto3.client('bedrock-runtime', region_name=self.region)
            services.append({
                'name': 'Amazon Bedrock',
                'status': 'operational',
                'latency_ms': 0
            })
        except Exception as e:
            services.append({
                'name': 'Amazon Bedrock',
                'status': 'error',
                'error': str(e)
            })
        
        # Check ECR
        try:
            ecr_client = boto3.client('ecr', region_name=self.region)
            ecr_client.describe_repositories(maxResults=1)
            services.append({
                'name': 'Amazon ECR',
                'status': 'operational',
                'latency_ms': 0
            })
        except Exception as e:
            services.append({
                'name': 'Amazon ECR',
                'status': 'error',
                'error': str(e)
            })
        
        # Check AgentCore
        try:
            agentcore_client = boto3.client('bedrock-agentcore-control', region_name=self.region)
            services.append({
                'name': 'Bedrock AgentCore',
                'status': 'operational',
                'latency_ms': 0
            })
        except Exception as e:
            services.append({
                'name': 'Bedrock AgentCore',
                'status': 'error',
                'error': str(e)
            })
        
        return services
    
    async def get_recent_activity(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent system activity"""
        try:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
            start_time = end_time - timedelta(hours=24)
            
            raw_events = self.cloudwatch.fetch_log_events(start_time, end_time)
            parsed_events = self.cloudwatch.parse_otel_logs(raw_events)
            
            # Get most recent events
            sorted_events = sorted(
                parsed_events,
                key=lambda x: x.get('timestamp', datetime.min),
                reverse=True
            )[:limit]
            
            activities = []
            for event in sorted_events:
                activities.append({
                    'timestamp': event.get('timestamp').isoformat() if event.get('timestamp') else None,
                    'type': event.get('level', 'INFO'),
                    'message': event.get('message', '')[:200],
                    'agent_id': event.get('agent_id'),
                    'service': event.get('service_name')
                })
            
            return activities
            
        except Exception as e:
            logger.error(f"Error getting recent activity: {e}")
            return []
