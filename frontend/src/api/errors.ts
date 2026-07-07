/**
 * Error analysis API endpoints
 */
import apiClient from './client';
import {
  LogEvent,
  ErrorAnalysis,
  TraceAnalysis,
  ErrorPattern,
  ErrorLogFilters,
} from '../types/error';

export const errorApi = {
  // Get error logs
  getErrorLogs: async (filters: ErrorLogFilters = {}): Promise<LogEvent[]> => {
    const params = new URLSearchParams();
    if (filters.agent_id) params.append('agent_id', filters.agent_id);
    if (filters.log_group) params.append('log_group', filters.log_group);
    if (filters.start_time) params.append('start_time', filters.start_time);
    if (filters.end_time) params.append('end_time', filters.end_time);
    if (filters.error_type) params.append('error_type', filters.error_type);
    if (filters.severity) params.append('severity', filters.severity);
    if (filters.limit) params.append('limit', filters.limit.toString());

    const response = await apiClient.get(`/errors/logs?${params.toString()}`);
    return response.data;
  },

  // Analyze errors
  analyzeErrors: async (
    agentId?: string,
    startTime?: string,
    endTime?: string
  ): Promise<ErrorAnalysis> => {
    const params = new URLSearchParams();
    if (agentId) params.append('agent_id', agentId);
    if (startTime) params.append('start_time', startTime);
    if (endTime) params.append('end_time', endTime);

    const response = await apiClient.get(`/errors/analyze?${params.toString()}`);
    return response.data;
  },

  // Get trace errors
  getTraceErrors: async (
    startTime?: string,
    endTime?: string,
    filterExpression?: string
  ): Promise<TraceAnalysis> => {
    const params = new URLSearchParams();
    if (startTime) params.append('start_time', startTime);
    if (endTime) params.append('end_time', endTime);
    if (filterExpression) params.append('filter_expression', filterExpression);

    const response = await apiClient.get(`/errors/traces?${params.toString()}`);
    return response.data;
  },

  // Detect error patterns
  detectPatterns: async (
    agentId?: string,
    startTime?: string,
    endTime?: string
  ): Promise<ErrorPattern[]> => {
    const params = new URLSearchParams();
    if (agentId) params.append('agent_id', agentId);
    if (startTime) params.append('start_time', startTime);
    if (endTime) params.append('end_time', endTime);

    const response = await apiClient.get(`/errors/patterns?${params.toString()}`);
    return response.data;
  },

  // Get error types
  getErrorTypes: async (): Promise<{ error_types: { type: string; description: string }[] }> => {
    const response = await apiClient.get('/errors/types');
    return response.data;
  },
};
