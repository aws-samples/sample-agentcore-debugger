/**
 * TypeScript types for Error analysis
 */

export const ErrorSeverity = {
  FATAL: 'FATAL',
  ERROR: 'ERROR',
  WARN: 'WARN',
  WARNING: 'WARNING',
  INFO: 'INFO',
  UNKNOWN: 'UNKNOWN',
} as const;

export type ErrorSeverity = typeof ErrorSeverity[keyof typeof ErrorSeverity];

export const ErrorType = {
  TIMEOUT: 'timeout',
  AUTHENTICATION: 'authentication',
  RATE_LIMIT: 'rate_limit',
  VALIDATION: 'validation',
  SERVICE_ERROR: 'service_error',
  NETWORK: 'network',
  PERMISSION: 'permission',
  RESOURCE_NOT_FOUND: 'resource_not_found',
  CONFIGURATION: 'configuration',
  DEPENDENCY: 'dependency',
  MEMORY: 'memory',
  DISK: 'disk',
  DATABASE: 'database',
  GENERIC_ERROR: 'generic_error',
  UNKNOWN: 'unknown',
} as const;

export type ErrorType = typeof ErrorType[keyof typeof ErrorType];

export interface LogEvent {
  timestamp: string;
  log_group: string;
  log_stream?: string;
  level: string;
  message: string;
  body?: string;
  trace_id?: string;
  span_id?: string;
  service_name?: string;
  agent_id?: string;
  session_id?: string;
  error_type?: string;
  stack_trace?: string;
  error_message?: string;
  raw_message?: string;
  structured_data?: Record<string, any>;
}

export interface ErrorSummary {
  error_type: string;
  count: number;
  percentage: number;
  sample_messages: string[];
}

export interface ErrorAnalysis {
  total_errors: number;
  total_warnings: number;
  error_rate: number;
  time_range_start: string;
  time_range_end: string;
  errors_by_type: ErrorSummary[];
  errors_by_severity: Record<string, number>;
  recent_errors: LogEvent[];
  affected_agents: string[];
  affected_services: string[];
}

export interface XRaySpan {
  trace_id: string;
  segment_id?: string;
  parent_id?: string;
  name: string;
  start_time?: number;
  end_time?: number;
  duration?: number;
  error: boolean;
  fault: boolean;
  cause?: any;
  annotations: Record<string, any>;
  metadata: Record<string, any>;
  service_name?: string;
  subsegment_name?: string;
  http_status?: number;
  error_message?: string;
  exception_type?: string;
}

export interface TraceAnalysis {
  total_traces: number;
  total_segments: number;
  error_count: number;
  fault_count: number;
  avg_duration: number;
  min_duration: number;
  max_duration: number;
  service_performance: Record<string, any>;
  error_spans: XRaySpan[];
}

export interface ErrorPattern {
  pattern_id: string;
  error_type: string;
  frequency: number;
  first_seen: string;
  last_seen: string;
  sample_message: string;
  affected_agents: string[];
  suggested_fix?: string;
}

// Filter types
export interface ErrorLogFilters {
  agent_id?: string;
  log_group?: string;
  start_time?: string;
  end_time?: string;
  error_type?: string;
  severity?: string;
  limit?: number;
}
