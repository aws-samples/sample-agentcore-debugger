/**
 * React hooks for error data fetching
 */
import { useQuery, UseQueryResult } from '@tanstack/react-query';
import { errorApi } from '../api/errors';
import {
  LogEvent,
  ErrorAnalysis,
  TraceAnalysis,
  ErrorPattern,
  ErrorLogFilters,
} from '../types/error';

// Query keys
export const errorKeys = {
  all: ['errors'] as const,
  logs: () => [...errorKeys.all, 'logs'] as const,
  logsList: (filters: ErrorLogFilters) => [...errorKeys.logs(), filters] as const,
  analysis: () => [...errorKeys.all, 'analysis'] as const,
  analysisByAgent: (agentId?: string, startTime?: string, endTime?: string) =>
    [...errorKeys.analysis(), agentId, startTime, endTime] as const,
  traces: () => [...errorKeys.all, 'traces'] as const,
  tracesByTime: (startTime?: string, endTime?: string) =>
    [...errorKeys.traces(), startTime, endTime] as const,
  patterns: () => [...errorKeys.all, 'patterns'] as const,
  patternsByAgent: (agentId?: string, startTime?: string, endTime?: string) =>
    [...errorKeys.patterns(), agentId, startTime, endTime] as const,
  types: () => [...errorKeys.all, 'types'] as const,
};

// Hook to get error logs
export const useErrorLogs = (
  filters: ErrorLogFilters = {},
  options?: { enabled?: boolean }
): UseQueryResult<LogEvent[], Error> => {
  return useQuery({
    queryKey: errorKeys.logsList(filters),
    queryFn: () => errorApi.getErrorLogs(filters),
    staleTime: 30000, // 30 seconds
    enabled: options?.enabled ?? true,
  });
};

// Hook to analyze errors
export const useErrorAnalysis = (
  agentId?: string,
  startTime?: string,
  endTime?: string,
  options?: { enabled?: boolean }
): UseQueryResult<ErrorAnalysis, Error> => {
  return useQuery({
    queryKey: errorKeys.analysisByAgent(agentId, startTime, endTime),
    queryFn: () => errorApi.analyzeErrors(agentId, startTime, endTime),
    staleTime: 60000, // 1 minute
    enabled: options?.enabled ?? true,
  });
};

// Hook to get trace errors
export const useTraceErrors = (
  startTime?: string,
  endTime?: string,
  options?: { enabled?: boolean }
): UseQueryResult<TraceAnalysis, Error> => {
  return useQuery({
    queryKey: errorKeys.tracesByTime(startTime, endTime),
    queryFn: () => errorApi.getTraceErrors(startTime, endTime),
    staleTime: 60000, // 1 minute
    enabled: options?.enabled ?? true,
  });
};

// Hook to detect error patterns
export const useErrorPatterns = (
  agentId?: string,
  startTime?: string,
  endTime?: string,
  options?: { enabled?: boolean }
): UseQueryResult<ErrorPattern[], Error> => {
  return useQuery({
    queryKey: errorKeys.patternsByAgent(agentId, startTime, endTime),
    queryFn: () => errorApi.detectPatterns(agentId, startTime, endTime),
    staleTime: 120000, // 2 minutes
    enabled: options?.enabled ?? true,
  });
};

// Hook to get error types
export const useErrorTypes = (
  options?: { enabled?: boolean }
): UseQueryResult<{ error_types: { type: string; description: string }[] }, Error> => {
  return useQuery({
    queryKey: errorKeys.types(),
    queryFn: () => errorApi.getErrorTypes(),
    staleTime: 300000, // 5 minutes
    enabled: options?.enabled ?? true,
  });
};
