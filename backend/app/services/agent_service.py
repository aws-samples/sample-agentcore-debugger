"""
Service layer for agent operations
Reuses existing collectors from the main app
"""
import sys
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone

# Add parent directory to path to import existing modules
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from src.collectors.agent_discovery import AgentDiscovery
from src.collectors.metrics_collector import MetricsCollector
from app.models.agent import (
    Agent, AgentListResponse, AgentHealthStatus, 
    AgentMetrics, AgentConfiguration, AgentStatus, AgentSource
)


class AgentService:
    """Service for agent-related operations"""
    
    def __init__(self):
        self.agent_discovery = AgentDiscovery()
        self.metrics_collector = MetricsCollector()
    
    async def get_agents(
        self, 
        status: Optional[str] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> AgentListResponse:
        """Get list of agents with filters"""
        
        # Discover all agents
        agents_data = self.agent_discovery.discover_agents()
        
        # Apply filters
        if status:
            agents_data = [a for a in agents_data if a.get('status') == status]
        
        if source:
            agents_data = [a for a in agents_data if a.get('source') == source]
        
        if search:
            search_lower = search.lower()
            agents_data = [
                a for a in agents_data 
                if search_lower in a.get('name', '').lower() 
                or search_lower in a.get('agent_id', '').lower()
            ]
        
        # Calculate metrics
        total = len(agents_data)
        active = len([a for a in agents_data if a.get('status') in ['PREPARED', 'ACTIVE']])
        errors = len([a for a in agents_data if a.get('status') in ['FAILED', 'ERROR']])
        runtime_count = len([a for a in agents_data if a.get('source') == 'agentcore-runtime'])
        
        # Apply pagination
        paginated_agents = agents_data[offset:offset + limit]
        
        # Convert to Agent models
        agents = []
        for agent_data in paginated_agents:
            try:
                agent = Agent(
                    agent_id=agent_data.get('agent_id', 'unknown'),
                    name=agent_data.get('name', 'Unknown'),
                    status=AgentStatus(agent_data.get('status', 'UNKNOWN')),
                    source=AgentSource(agent_data.get('source', 'unknown')),
                    created_at=agent_data.get('created_at'),
                    updated_at=agent_data.get('updated_at'),
                    last_activity=agent_data.get('last_activity'),
                    log_group=agent_data.get('log_group'),
                    stored_bytes=agent_data.get('stored_bytes'),
                    runtime=agent_data.get('runtime'),
                    memory_size=agent_data.get('memory_size'),
                    timeout=agent_data.get('timeout')
                )
                agents.append(agent)
            except Exception as e:
                print(f"Error converting agent data: {e}")
                continue
        
        return AgentListResponse(
            agents=agents,
            total=total,
            active=active,
            errors=errors,
            runtime_count=runtime_count
        )
    
    async def get_agent_by_id(self, agent_id: str) -> Optional[Agent]:
        """Get single agent by ID"""
        agents_data = self.agent_discovery.discover_agents()
        
        for agent_data in agents_data:
            if agent_data.get('agent_id') == agent_id:
                return Agent(
                    agent_id=agent_data.get('agent_id', 'unknown'),
                    name=agent_data.get('name', 'Unknown'),
                    status=AgentStatus(agent_data.get('status', 'UNKNOWN')),
                    source=AgentSource(agent_data.get('source', 'unknown')),
                    created_at=agent_data.get('created_at'),
                    updated_at=agent_data.get('updated_at'),
                    last_activity=agent_data.get('last_activity'),
                    log_group=agent_data.get('log_group'),
                    stored_bytes=agent_data.get('stored_bytes'),
                    runtime=agent_data.get('runtime'),
                    memory_size=agent_data.get('memory_size'),
                    timeout=agent_data.get('timeout')
                )
        
        return None
    
    async def get_agent_health(self, agent_id: str, source: str) -> AgentHealthStatus:
        """Get agent health status"""
        health_data = self.agent_discovery.get_agent_health_status(agent_id, source)
        
        return AgentHealthStatus(
            status=health_data.get('status', 'unknown'),
            error_rate=health_data.get('error_rate', 0.0),
            avg_response_time=health_data.get('avg_response_time', 0.0)
        )
    
    async def get_agent_metrics(
        self, 
        agent_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> AgentMetrics:
        """Get agent metrics from ADOT"""
        
        # Default time range: last 24 hours
        if not end_time:
            end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        if not start_time:
            start_time = end_time - timedelta(days=1)
        
        # Strip -DEFAULT suffix if present
        runtime_id = agent_id.replace('-DEFAULT', '') if agent_id.endswith('-DEFAULT') else agent_id
        
        # Get metrics from collector
        metrics_data = self.metrics_collector.get_agent_metrics(
            agent_runtime_id=runtime_id,
            start_time=start_time,
            end_time=end_time
        )
        
        return AgentMetrics(**metrics_data)
    
    async def get_agent_configuration(self, agent_id: str, source: str) -> AgentConfiguration:
        """Get agent configuration"""
        config_data = self.agent_discovery.get_agent_configuration(agent_id, source)
        
        return AgentConfiguration(config=config_data or {})
