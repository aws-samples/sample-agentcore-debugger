/**
 * TypeScript types for Agent-related data
 */

export const AgentStatus = {
  ACTIVE: 'ACTIVE',
  PREPARED: 'PREPARED',
  CREATING: 'CREATING',
  UPDATING: 'UPDATING',
  FAILED: 'FAILED',
  ERROR: 'ERROR',
  DELETING: 'DELETING',
  UNKNOWN: 'UNKNOWN',
} as const;

export type AgentStatus = typeof AgentStatus[keyof typeof AgentStatus];

export const AgentSource = {
  AGENTCORE_RUNTIME: 'agentcore-runtime',
} as const;

export type AgentSource = typeof AgentSource[keyof typeof AgentSource];

export interface Agent {
  agent_id: string;
  name: string;
  status: AgentStatus;
  source: AgentSource;
  created_at?: string;
  updated_at?: string;
  last_activity?: string;
  log_group?: string;
  stored_bytes?: number;
  runtime?: string;
  memory_size?: number;
  timeout?: number;
}

export interface AgentListResponse {
  agents: Agent[];
  total: number;
  active: number;
  errors: number;
  runtime_count: number;
}

export interface AgentHealthStatus {
  status: string;
  error_rate: number;
  avg_response_time: number;
}

export interface AgentMetrics {
  runtime_sessions: number;
  runtime_invocations: number;
  runtime_errors: number;
  runtime_faults: number;
  runtime_throttles: number;
  runtime_error_rate: number;
  runtime_throttle_rate: number;
  vcpu_consumption_hours: number;
  memory_consumption_gb_hours: number;
  avg_duration_seconds: number;
  max_duration_seconds: number;
  min_duration_seconds: number;
  recent_invocations: any[];
}

export interface AgentConfiguration {
  config: Record<string, any>;
}

// Filter types
export interface AgentFilters {
  status?: string;
  source?: string;
  search?: string;
  limit?: number;
  offset?: number;
}
