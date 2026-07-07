"""
Agent Discovery Service for AgentCore Debugger Assistant
"""
import boto3
from botocore.config import Config
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from botocore.exceptions import ClientError

# Optional Streamlit import for UI features
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False
    # Create a dummy st object for standalone usage
    class DummySt:
        class session_state:
            @staticmethod
            def get(key, default=None):
                return default
        @staticmethod
        def warning(msg):
            print(f"WARNING: {msg}")
        @staticmethod
        def write(msg):
            print(msg)
    st = DummySt()


class AgentDiscovery:
    """Discovers and monitors AgentCore agents"""
    
    def __init__(self, region: str = 'us-east-1'):
        """Initialize agent discovery service
        
        Args:
            region: AWS region for services
        """
        self.region = region
        _retry = Config(retries={"mode": "adaptive", "max_attempts": 10})
        self.bedrock_client = boto3.client('bedrock-agent', region_name=region, config=_retry)
        self.ssm_client = boto3.client('ssm', region_name=region)
        self.cloudwatch_client = boto3.client('cloudwatch', region_name=region)
        self.lambda_client = boto3.client('lambda', region_name=region)
    
    def discover_agents(self) -> List[Dict[str, Any]]:
        """Discover deployed AgentCore agents (runtime agents only, not Bedrock Agents)
        
        Returns:
            List of discovered AgentCore runtime agents with metadata
        """
        agents = []
        
        # ONLY discover AgentCore runtime agents from log groups
        # This excludes old Bedrock Agents service and focuses on AgentCore deployments
        runtime_agents = self._discover_agentcore_runtime_agents()
        agents.extend(runtime_agents)
        
        # Remove duplicates based on agent_id
        unique_agents = {}
        for agent in agents:
            agent_id = agent.get('agent_id')
            if agent_id and agent_id not in unique_agents:
                unique_agents[agent_id] = agent
            elif agent_id:
                # Merge information from multiple sources
                existing = unique_agents[agent_id]
                for key, value in agent.items():
                    if key not in existing or not existing[key]:
                        existing[key] = value
        
        return list(unique_agents.values())
    
    def _discover_bedrock_agents(self) -> List[Dict[str, Any]]:
        """Discover agents from Bedrock Agent service"""
        agents = []
        
        try:
            response = self.bedrock_client.list_agents()
            
            for agent in response.get('agentSummaries', []):
                agent_info = {
                    'agent_id': agent['agentId'],
                    'name': agent['agentName'],
                    'status': agent['agentStatus'],
                    'created_at': agent.get('createdAt'),
                    'updated_at': agent.get('updatedAt'),
                    'description': agent.get('description', ''),
                    'source': 'bedrock-agent',
                    'agent_version': agent.get('latestAgentVersion', '1'),
                    'foundation_model': None,
                    'instruction': None
                }
                
                # Get detailed agent information
                try:
                    detail_response = self.bedrock_client.get_agent(
                        agentId=agent['agentId']
                    )
                    agent_details = detail_response.get('agent', {})
                    agent_info.update({
                        'foundation_model': agent_details.get('foundationModel'),
                        'instruction': agent_details.get('instruction'),
                        'role_arn': agent_details.get('agentResourceRoleArn'),
                        'idle_timeout': agent_details.get('idleSessionTTLInSeconds'),
                        'customer_encryption_key': agent_details.get('customerEncryptionKeyArn')
                    })
                except ClientError:
                    # Continue with basic info if detailed info fails
                    pass
                
                agents.append(agent_info)
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDeniedException':
                st.warning("No access to Bedrock Agent service. Check IAM permissions.")
            else:
                st.warning(f"Could not list Bedrock agents: {e}")
        
        return agents
    
    def _discover_parameter_store_agents(self) -> List[Dict[str, Any]]:
        """Discover agents from Parameter Store"""
        agents = []
        
        try:
            # Common parameter paths for AgentCore
            parameter_paths = [
                '/agentcore/agents/',
                '/bedrock/agents/',
                '/strands/agents/'
            ]
            
            for path in parameter_paths:
                try:
                    response = self.ssm_client.get_parameters_by_path(
                        Path=path,
                        Recursive=True
                    )
                    
                    for param in response.get('Parameters', []):
                        agent_name = param['Name'].split('/')[-1]
                        
                        agent_info = {
                            'agent_id': agent_name,
                            'name': agent_name,
                            'arn': param['Value'],
                            'last_modified': param['LastModifiedDate'],
                            'source': 'parameter-store',
                            'parameter_path': param['Name'],
                            'status': 'UNKNOWN'
                        }
                        
                        agents.append(agent_info)
                
                except ClientError:
                    # Path doesn't exist or no access, continue
                    continue
        
        except ClientError as e:
            st.warning(f"Could not query Parameter Store: {e}")
        
        return agents
    
    def _discover_lambda_agents(self) -> List[Dict[str, Any]]:
        """Discover Lambda-based agents"""
        agents = []
        
        try:
            response = self.lambda_client.list_functions()
            
            for function in response.get('Functions', []):
                function_name = function['FunctionName']
                
                # Check if this is likely an AgentCore function
                if any(keyword in function_name.lower() for keyword in 
                      ['agent', 'strands', 'bedrock', 'agentcore']):
                    
                    # Get tags to confirm it's an AgentCore agent
                    try:
                        tags_response = self.lambda_client.list_tags(
                            Resource=function['FunctionArn']
                        )
                        tags = tags_response.get('Tags', {})
                        
                        # Check for AgentCore-specific tags
                        if any(key.lower() in ['agentcore', 'agent-type', 'strands'] 
                              for key in tags.keys()):
                            
                            agent_info = {
                                'agent_id': function_name,
                                'name': function_name,
                                'status': 'ACTIVE' if function['State'] == 'Active' else function['State'],
                                'created_at': function.get('LastModified'),
                                'updated_at': function.get('LastModified'),
                                'source': 'lambda',
                                'runtime': function.get('Runtime'),
                                'memory_size': function.get('MemorySize'),
                                'timeout': function.get('Timeout'),
                                'function_arn': function['FunctionArn'],
                                'tags': tags
                            }
                            
                            agents.append(agent_info)
                    
                    except ClientError:
                        # Can't get tags, skip this function
                        continue
        
        except ClientError as e:
            st.warning(f"Could not list Lambda functions: {e}")
        
        return agents
    
    def _discover_agentcore_runtime_agents(self) -> List[Dict[str, Any]]:
        """Discover AgentCore agents from the actual AgentCore API (not log groups)"""
        agents = []
        
        try:
            # Use the AgentCore control plane API to list actual deployed agents
            agentcore_client = boto3.client('bedrock-agentcore-control', region_name=self.region, config=Config(retries={"mode": "adaptive", "max_attempts": 10}))
            logs_client = boto3.client('logs', region_name=self.region)
            
            next_token = None
            while True:
                if next_token:
                    response = agentcore_client.list_agent_runtimes(nextToken=next_token)
                else:
                    response = agentcore_client.list_agent_runtimes()
                
                for agent in response.get('agentRuntimes', []):
                    runtime_id = agent.get('agentRuntimeId', '')
                    agent_name = agent.get('agentRuntimeName', '')
                    status = agent.get('status', 'UNKNOWN')
                    
                    # Build log group name for this agent
                    log_group_name = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
                    
                    # Get log group info for storage size
                    stored_bytes = 0
                    try:
                        lg_response = logs_client.describe_log_groups(
                            logGroupNamePrefix=log_group_name,
                            limit=1
                        )
                        if lg_response.get('logGroups'):
                            stored_bytes = lg_response['logGroups'][0].get('storedBytes', 0)
                    except ClientError:
                        pass
                    
                    # Get last activity from logs
                    last_activity = self._get_last_log_activity(logs_client, log_group_name)
                    
                    created_at = agent.get('createdAt')
                    updated_at = agent.get('lastUpdatedAt')
                    
                    agent_info = {
                        'agent_id': f"{runtime_id}-DEFAULT",
                        'name': agent_name,
                        'status': status,
                        'created_at': created_at.timestamp() * 1000 if created_at else None,
                        'updated_at': updated_at if updated_at else last_activity,
                        'last_modified': updated_at if updated_at else last_activity,
                        'last_activity': last_activity,
                        'source': 'agentcore-runtime',
                        'log_group': log_group_name,
                        'stored_bytes': stored_bytes,
                        'arn': agent.get('agentRuntimeArn'),
                    }
                    
                    agents.append(agent_info)
                
                next_token = response.get('nextToken')
                if not next_token:
                    break
                    
        except ClientError as e:
            # Fallback: if AgentCore API fails, log the error
            import logging
            logging.warning(f"Could not list AgentCore runtimes: {e}")
        
        return agents
    
    def _get_last_log_activity(self, logs_client, log_group_name: str) -> Optional[datetime]:
        """Get the timestamp of the most recent log event in a log group"""
        try:
            # Get the most recent log stream (sorted by last event time)
            streams_response = logs_client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy='LastEventTime',
                descending=True,
                limit=1
            )
            
            streams = streams_response.get('logStreams', [])
            if streams and 'lastEventTime' in streams[0]:
                # Convert timestamp from milliseconds to datetime
                timestamp_ms = streams[0]['lastEventTime']
                return datetime.fromtimestamp(timestamp_ms / 1000)
            else:
                # No streams or events, return None
                return None
                
        except ClientError:
            # If we can't get log streams, return None
            return None
    
    def get_agent_metrics(self, agent_id: str, start_time: datetime, 
                         end_time: datetime) -> Dict[str, List[Dict[str, Any]]]:
        """Get performance metrics for a specific agent
        
        Args:
            agent_id: Agent identifier
            start_time: Start time for metrics
            end_time: End time for metrics
            
        Returns:
            Dictionary of metrics data
        """
        metrics = {}
        
        # Define metric queries based on AgentCore documentation
        # Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html
        metric_queries = [
            # AgentCore Runtime Metrics (primary metrics for AgentCore agents)
            ('Invocations', 'AWS/BedrockAgentCore/Runtime', 'Invocations', 'AgentRuntimeId'),
            ('Throttles', 'AWS/BedrockAgentCore/Runtime', 'Throttles', 'AgentRuntimeId'),
            ('SystemErrors', 'AWS/BedrockAgentCore/Runtime', 'SystemErrors', 'AgentRuntimeId'),
            ('UserErrors', 'AWS/BedrockAgentCore/Runtime', 'UserErrors', 'AgentRuntimeId'),
            ('Latency', 'AWS/BedrockAgentCore/Runtime', 'Latency', 'AgentRuntimeId'),
            ('TotalErrors', 'AWS/BedrockAgentCore/Runtime', 'TotalErrors', 'AgentRuntimeId'),
            ('SessionCount', 'AWS/BedrockAgentCore/Runtime', 'SessionCount', 'AgentRuntimeId'),
            
            # AgentCore Resource Usage Metrics
            ('CPUUsed', 'AWS/BedrockAgentCore/Runtime', 'CPUUsed-vCPUHours', 'AgentRuntimeId'),
            ('MemoryUsed', 'AWS/BedrockAgentCore/Runtime', 'MemoryUsed-GBHours', 'AgentRuntimeId'),
            
            # AgentCore Tool Metrics (for agents using built-in tools)
            ('ToolInvocations', 'AWS/BedrockAgentCore/Tools', 'Invocations', 'ToolId'),
            ('ToolThrottles', 'AWS/BedrockAgentCore/Tools', 'Throttles', 'ToolId'),
            ('ToolSystemErrors', 'AWS/BedrockAgentCore/Tools', 'SystemErrors', 'ToolId'),
            ('ToolUserErrors', 'AWS/BedrockAgentCore/Tools', 'UserErrors', 'ToolId'),
            ('ToolLatency', 'AWS/BedrockAgentCore/Tools', 'Latency', 'ToolId'),
            ('ToolDuration', 'AWS/BedrockAgentCore/Tools', 'Duration', 'ToolId'),
            
            # Legacy Bedrock Agent metrics (for backward compatibility)
            ('LegacyInvocations', 'AWS/Bedrock/Agents', 'InvocationCount', 'Operation'),
            ('LegacyServerErrors', 'AWS/Bedrock/Agents', 'InvocationServerErrors', 'Operation'),
            ('LegacyClientErrors', 'AWS/Bedrock/Agents', 'InvocationClientErrors', 'Operation'),
            ('LegacyLatency', 'AWS/Bedrock/Agents', 'TotalTime', 'Operation'),
            
            # Lambda metrics (for Lambda-based agents)
            ('LambdaInvocations', 'AWS/Lambda', 'Invocations', 'FunctionName'),
            ('LambdaErrors', 'AWS/Lambda', 'Errors', 'FunctionName'),
            ('LambdaDuration', 'AWS/Lambda', 'Duration', 'FunctionName'),
            ('LambdaThrottles', 'AWS/Lambda', 'Throttles', 'FunctionName'),
        ]
        
        # First, get all available metrics for bedrock-agentcore namespace
        available_metrics = self._get_available_agentcore_metrics()
        
        for metric_name, namespace, metric_stat, dimension_name in metric_queries:
            try:
                if namespace.startswith('AWS/BedrockAgentCore'):
                    # For AgentCore metrics, use the agent_id as the dimension value
                    # AgentCore metrics use specific dimension names based on the service
                    if dimension_name == 'AgentRuntimeId':
                        # Remove -DEFAULT suffix if present for AgentCore Runtime metrics
                        runtime_id = agent_id
                        if runtime_id.endswith('-DEFAULT'):
                            runtime_id = runtime_id[:-8]
                        dimensions = [{'Name': dimension_name, 'Value': runtime_id}]
                    elif dimension_name == 'ToolId':
                        # For tool metrics, we might need to discover tool IDs
                        # For now, skip tool metrics if we don't have a specific tool ID
                        metrics[metric_name] = []
                        continue
                    else:
                        dimensions = [{'Name': dimension_name, 'Value': agent_id}]
                    
                    response = self.cloudwatch_client.get_metric_statistics(
                        Namespace=namespace,
                        MetricName=metric_stat,
                        Dimensions=dimensions,
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=3600,  # 1 hour for AgentCore metrics (as per documentation)
                        Statistics=['Sum', 'Average', 'Maximum']
                    )
                    
                    datapoints = response.get('Datapoints', [])
                    datapoints.sort(key=lambda x: x['Timestamp'])
                    metrics[metric_name] = datapoints
                
                elif namespace == 'AWS/Bedrock/Agents':
                    # For legacy Bedrock Agents, use Operation dimension with InvokeAgent value
                    dimensions = [{'Name': 'Operation', 'Value': 'InvokeAgent'}]
                    
                    response = self.cloudwatch_client.get_metric_statistics(
                        Namespace=namespace,
                        MetricName=metric_stat,
                        Dimensions=dimensions,
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=300,  # 5 minutes
                        Statistics=['Sum', 'Average', 'Maximum']
                    )
                    
                    datapoints = response.get('Datapoints', [])
                    datapoints.sort(key=lambda x: x['Timestamp'])
                    metrics[metric_name] = datapoints
                
                else:
                    # For Lambda and other services, use the agent_id directly
                    dimensions = [{'Name': dimension_name, 'Value': agent_id}]
                    
                    response = self.cloudwatch_client.get_metric_statistics(
                        Namespace=namespace,
                        MetricName=metric_stat,
                        Dimensions=dimensions,
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=300,  # 5 minutes
                        Statistics=['Sum', 'Average', 'Maximum']
                    )
                    
                    datapoints = response.get('Datapoints', [])
                    datapoints.sort(key=lambda x: x['Timestamp'])
                    metrics[metric_name] = datapoints
                
            except ClientError as e:
                # Metric not available for this agent type, or no data
                metrics[metric_name] = []
                if st.session_state.get('show_debug', False):
                    st.write(f"Debug: Could not fetch {metric_name} for {agent_id}: {e}")
            except Exception as e:
                metrics[metric_name] = []
                if st.session_state.get('show_debug', False):
                    st.write(f"Debug: Error fetching {metric_name}: {e}")
        
        return metrics
    
    def _get_available_agentcore_metrics(self) -> List[Dict[str, Any]]:
        """Get all available metrics in the bedrock-agentcore namespace"""
        try:
            response = self.cloudwatch_client.list_metrics(Namespace='bedrock-agentcore')
            return response.get('Metrics', [])
        except ClientError:
            return []
    
    def get_agent_health_status(self, agent_id: str, agent_source: str) -> Dict[str, Any]:
        """Get current health status of an agent
        
        Args:
            agent_id: Agent identifier
            agent_source: Source of the agent (bedrock-agent, lambda, etc.)
            
        Returns:
            Health status information
        """
        health_status = {
            'status': 'UNKNOWN',
            'last_check': datetime.now(),
            'error_rate': 0.0,
            'avg_response_time': 0.0,
            'recent_errors': []
        }
        
        try:
            # Get recent metrics (last hour)
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=1)
            
            metrics = self.get_agent_metrics(agent_id, start_time, end_time)
            
            # Calculate error rate
            invocations = metrics.get('Invocations', []) or metrics.get('LambdaInvocations', [])
            errors = metrics.get('Errors', []) or metrics.get('LambdaErrors', [])
            
            total_invocations = sum(dp.get('Sum', 0) for dp in invocations)
            total_errors = sum(dp.get('Sum', 0) for dp in errors)
            
            if total_invocations > 0:
                health_status['error_rate'] = (total_errors / total_invocations) * 100
                health_status['status'] = 'HEALTHY' if health_status['error_rate'] < 5 else 'DEGRADED'
            
            # Calculate average response time
            durations = metrics.get('Duration', []) or metrics.get('LambdaDuration', [])
            if durations:
                avg_duration = sum(dp.get('Average', 0) for dp in durations) / len(durations)
                health_status['avg_response_time'] = avg_duration
            
            # Check for specific agent status (Bedrock agents)
            if agent_source == 'bedrock-agent':
                try:
                    response = self.bedrock_client.get_agent(agentId=agent_id)
                    agent_status = response.get('agent', {}).get('agentStatus', 'UNKNOWN')
                    
                    if agent_status == 'PREPARED':
                        health_status['status'] = 'HEALTHY'
                    elif agent_status in ['CREATING', 'UPDATING']:
                        health_status['status'] = 'UPDATING'
                    elif agent_status in ['FAILED', 'DELETING']:
                        health_status['status'] = 'ERROR'
                
                except ClientError:
                    pass
        
        except Exception as e:
            st.warning(f"Could not get health status for agent {agent_id}: {e}")
        
        return health_status
    
    def get_agent_configuration(self, agent_id: str, agent_source: str) -> Dict[str, Any]:
        """Get detailed configuration for an agent
        
        Args:
            agent_id: Agent identifier
            agent_source: Source of the agent
            
        Returns:
            Agent configuration details
        """
        config = {}
        
        if agent_source == 'bedrock-agent':
            try:
                response = self.bedrock_client.get_agent(agentId=agent_id)
                agent_data = response.get('agent', {})
                
                config = {
                    'foundation_model': agent_data.get('foundationModel'),
                    'instruction': agent_data.get('instruction'),
                    'role_arn': agent_data.get('agentResourceRoleArn'),
                    'idle_timeout': agent_data.get('idleSessionTTLInSeconds'),
                    'encryption_key': agent_data.get('customerEncryptionKeyArn'),
                    'prompt_override': agent_data.get('promptOverrideConfiguration'),
                    'guardrail_config': agent_data.get('guardrailConfiguration')
                }
                
                # Get knowledge bases
                try:
                    kb_response = self.bedrock_client.list_agent_knowledge_bases(
                        agentId=agent_id,
                        agentVersion='DRAFT'
                    )
                    config['knowledge_bases'] = kb_response.get('agentKnowledgeBaseSummaries', [])
                except ClientError:
                    config['knowledge_bases'] = []
                
                # Get action groups
                try:
                    ag_response = self.bedrock_client.list_agent_action_groups(
                        agentId=agent_id,
                        agentVersion='DRAFT'
                    )
                    config['action_groups'] = ag_response.get('actionGroupSummaries', [])
                except ClientError:
                    config['action_groups'] = []
            
            except ClientError as e:
                st.warning(f"Could not get configuration for Bedrock agent {agent_id}: {e}")
        
        elif agent_source == 'lambda':
            try:
                response = self.lambda_client.get_function(FunctionName=agent_id)
                function_config = response.get('Configuration', {})
                
                config = {
                    'runtime': function_config.get('Runtime'),
                    'handler': function_config.get('Handler'),
                    'memory_size': function_config.get('MemorySize'),
                    'timeout': function_config.get('Timeout'),
                    'environment_variables': function_config.get('Environment', {}).get('Variables', {}),
                    'layers': function_config.get('Layers', []),
                    'vpc_config': function_config.get('VpcConfig'),
                    'dead_letter_config': function_config.get('DeadLetterConfig')
                }
            
            except ClientError as e:
                st.warning(f"Could not get configuration for Lambda agent {agent_id}: {e}")
        
        return config
    
    def test_agent_connectivity(self, agent_id: str, agent_source: str) -> bool:
        """Test if agent is accessible and responding
        
        Args:
            agent_id: Agent identifier
            agent_source: Source of the agent
            
        Returns:
            True if agent is accessible, False otherwise
        """
        try:
            if agent_source == 'bedrock-agent':
                # Try to get agent details
                self.bedrock_client.get_agent(agentId=agent_id)
                return True
            
            elif agent_source == 'lambda':
                # Try to get function configuration
                self.lambda_client.get_function(FunctionName=agent_id)
                return True
            
            return False
        
        except ClientError:
            return False