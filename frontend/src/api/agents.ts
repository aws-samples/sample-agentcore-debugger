/**
 * Agent API endpoints
 */
import apiClient from './client';
import {
  Agent,
  AgentListResponse,
  AgentHealthStatus,
  AgentMetrics,
  AgentConfiguration,
  AgentFilters,
} from '../types/agent';

export const agentApi = {
  // Get list of agents
  getAgents: async (filters: AgentFilters = {}): Promise<AgentListResponse> => {
    const params = new URLSearchParams();
    if (filters.status) params.append('status', filters.status);
    if (filters.source) params.append('source', filters.source);
    if (filters.search) params.append('search', filters.search);
    if (filters.limit) params.append('limit', filters.limit.toString());
    if (filters.offset) params.append('offset', filters.offset.toString());

    const response = await apiClient.get(`/agents?${params.toString()}`);
    return response.data;
  },

  // Get single agent
  getAgent: async (agentId: string): Promise<Agent> => {
    const response = await apiClient.get(`/agents/${agentId}`);
    return response.data;
  },

  // Get agent health
  getAgentHealth: async (agentId: string, source: string): Promise<AgentHealthStatus> => {
    const response = await apiClient.get(`/agents/${agentId}/health?source=${source}`);
    return response.data;
  },

  // Get agent metrics
  getAgentMetrics: async (
    agentId: string,
    startTime?: string,
    endTime?: string
  ): Promise<AgentMetrics> => {
    const params = new URLSearchParams();
    if (startTime) params.append('start_time', startTime);
    if (endTime) params.append('end_time', endTime);

    const response = await apiClient.get(`/agents/${agentId}/metrics?${params.toString()}`);
    return response.data;
  },

  // Get agent configuration
  getAgentConfiguration: async (agentId: string, source: string): Promise<AgentConfiguration> => {
    const response = await apiClient.get(`/agents/${agentId}/configuration?source=${source}`);
    return response.data;
  },

  // Generate test error for test-customer-agent
  generateTestError: async (
    agentId: string,
    errorType: 'order' | 'score' | 'recommend' | 'status' | 'module' = 'order',
    agentArn?: string
  ): Promise<{
    status: string;
    agent_id: string;
    error_type: string;
    prompt: string;
    message: string;
  }> => {
    const params = new URLSearchParams();
    params.append('error_type', errorType);
    if (agentArn) {
      params.append('agent_arn', agentArn);
    }
    const response = await apiClient.post(
      `/agents/${agentId}/generate-test-error?${params.toString()}`
    );
    return response.data;
  },

  // List deployed agents from Amazon Bedrock AgentCore
  listDeployedAgents: async (region: string = 'us-east-1'): Promise<{
    agents: Array<{
      name: string;
      arn: string;
      id: string;
      status: string;
      version: string;
      lastUpdatedAt: string | null;
    }>;
    region: string;
  }> => {
    const response = await apiClient.get(`/agents/deployed?region=${region}`);
    return response.data;
  },
};
