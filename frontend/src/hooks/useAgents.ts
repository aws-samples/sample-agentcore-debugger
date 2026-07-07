/**
 * React hooks for agent data fetching
 */
import { useQuery, UseQueryResult } from '@tanstack/react-query';
import { agentApi } from '../api/agents';
import {
  Agent,
  AgentListResponse,
  AgentHealthStatus,
  AgentMetrics,
  AgentConfiguration,
  AgentFilters,
} from '../types/agent';

// Query keys
export const agentKeys = {
  all: ['agents'] as const,
  lists: () => [...agentKeys.all, 'list'] as const,
  list: (filters: AgentFilters) => [...agentKeys.lists(), filters] as const,
  details: () => [...agentKeys.all, 'detail'] as const,
  detail: (id: string) => [...agentKeys.details(), id] as const,
  health: (id: string, source: string) => [...agentKeys.detail(id), 'health', source] as const,
  metrics: (id: string, startTime?: string, endTime?: string) => 
    [...agentKeys.detail(id), 'metrics', startTime, endTime] as const,
  config: (id: string, source: string) => [...agentKeys.detail(id), 'config', source] as const,
};

// Hook to get list of agents
export const useAgents = (
  filters: AgentFilters = {},
  options?: { enabled?: boolean }
): UseQueryResult<AgentListResponse, Error> => {
  return useQuery({
    queryKey: agentKeys.list(filters),
    queryFn: () => agentApi.getAgents(filters),
    staleTime: 30000, // 30 seconds
    enabled: options?.enabled ?? true,
  });
};

// Hook to get single agent
export const useAgent = (
  agentId: string,
  options?: { enabled?: boolean }
): UseQueryResult<Agent, Error> => {
  return useQuery({
    queryKey: agentKeys.detail(agentId),
    queryFn: () => agentApi.getAgent(agentId),
    staleTime: 60000, // 1 minute
    enabled: (options?.enabled ?? true) && !!agentId,
  });
};

// Hook to get agent health
export const useAgentHealth = (
  agentId: string,
  source: string,
  options?: { enabled?: boolean }
): UseQueryResult<AgentHealthStatus, Error> => {
  return useQuery({
    queryKey: agentKeys.health(agentId, source),
    queryFn: () => agentApi.getAgentHealth(agentId, source),
    staleTime: 30000, // 30 seconds
    enabled: (options?.enabled ?? true) && !!agentId && !!source,
  });
};

// Hook to get agent metrics
export const useAgentMetrics = (
  agentId: string,
  startTime?: string,
  endTime?: string,
  options?: { enabled?: boolean }
): UseQueryResult<AgentMetrics, Error> => {
  return useQuery({
    queryKey: agentKeys.metrics(agentId, startTime, endTime),
    queryFn: () => agentApi.getAgentMetrics(agentId, startTime, endTime),
    staleTime: 60000, // 1 minute
    enabled: (options?.enabled ?? true) && !!agentId,
  });
};

// Hook to get agent configuration
export const useAgentConfiguration = (
  agentId: string,
  source: string,
  options?: { enabled?: boolean }
): UseQueryResult<AgentConfiguration, Error> => {
  return useQuery({
    queryKey: agentKeys.config(agentId, source),
    queryFn: () => agentApi.getAgentConfiguration(agentId, source),
    staleTime: 300000, // 5 minutes
    enabled: (options?.enabled ?? true) && !!agentId && !!source,
  });
};
