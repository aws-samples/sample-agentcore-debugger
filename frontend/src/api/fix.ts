/**
 * Fix workflow API client
 */
import { apiClient } from './client';

// Types
export interface SampleEvent {
  timestamp?: string;
  message: string;
  trace_id?: string;
}

export interface ErrorCluster {
  pattern_id: string;
  error_type: string;
  error_message: string;
  count: number;
  first_seen?: string;
  last_seen?: string;
  sample_events: SampleEvent[];
  stack_trace?: string;
  affected_files: string[];
  status: 'pending' | 'analyzing' | 'awaiting_choice' | 'in_progress' | 'fixed' | 'failed' | 'skipped';
}

export interface SuppressedError {
  message: string;
  original_count: number;
  suppressed_count: number;
  error_type: string;
  severity: string;
}

export interface SuppressionSummary {
  total_original_errors: number;
  total_unique_patterns: number;
  total_suppressed: number;
  suppression_rate: number;
  top_suppressed_errors: SuppressedError[];
}

export interface ErrorClustersResponse {
  clusters: ErrorCluster[];
  suppression_summary: SuppressionSummary;
}

export interface FixResult {
  pattern_id: string;
  status: 'pending' | 'analyzing' | 'awaiting_choice' | 'in_progress' | 'fixed' | 'failed' | 'skipped';
  workflow_type: 'package_only' | 'code_fix_required' | 'mixed';
  fixed_files: Record<string, string>;
  original_files?: Record<string, string>;  // Original file contents for diff comparison (optional)
  code_agent_summary: string;
  package_recommendations: Array<Record<string, unknown>>;
  library_agent_output: string;
  git_info?: Record<string, unknown>;
  working_directory: string;
  error_classification: Record<string, unknown>;
  user_options: string[];
  message: string;
  // Optional fields for UI state
  git_diff?: string;
  modified_files?: string[];
}

export interface ErrorAnalysisResult {
  status: string;
  analysis: Record<string, unknown>;
  classification: Record<string, unknown>;
  recommendations: string[];
  suggested_fix?: string;
  confidence: number;
  error?: string;
}

export interface DeployedAgent {
  name: string;
  arn: string;
  id: string;
  status: string;
  version: string;
  lastUpdatedAt: string | null;
}

export interface ListDeployedAgentsResult {
  agents: DeployedAgent[];
  region: string;
}

export interface TestDeployedAgentResult {
  status: string;
  prompt: string;
  response?: string;
  parsed_response?: Record<string, unknown>;
  agent_arn: string;
  session_id: string;
  error?: string;
}

export type UserChoice = 'library' | 'code' | 'both' | 'skip';

// API functions
export const fixApi = {
  /**
   * Get error clusters for an agent with suppression summary
   */
  getErrorClusters: async (
    agentId: string,
    params?: {
      start_time?: string;
      end_time?: string;
      limit?: number;
      refresh?: boolean;
    }
  ): Promise<ErrorClustersResponse> => {
    const response = await apiClient.get<ErrorClustersResponse>(`/fix/clusters/${agentId}`, { params });
    return response.data;
  },

  /**
   * Analyze an error cluster
   */
  analyzeError: async (
    agentId: string,
    errorCluster: ErrorCluster
  ): Promise<ErrorAnalysisResult> => {
    const response = await apiClient.post<ErrorAnalysisResult>('/fix/analyze', {
      agent_id: agentId,
      error_cluster: errorCluster,
    });
    return response.data;
  },

  /**
   * Get job status for async fix workflow
   */
  getJobStatus: async (jobId: string): Promise<{
    job_id: string;
    status: string;
    result?: FixResult;
    error?: string;
  }> => {
    const response = await apiClient.get(`/fix/job/${jobId}`);
    return response.data;
  },

  /**
   * Start fix workflow for a pattern (async with polling)
   * @param isFixAll - If true, use shared workspace (Fix All mode). If false, create separate workspace (Fix This).
   * @param fixAllSessionId - Unique session ID for Fix All workspace isolation (ensures each user gets their own workspace)
   * @param preAnalysis - Pre-computed analysis from analyzeError (avoids redundant classification - saves ~10s)
   */
  startFixWorkflow: async (
    agentId: string,
    patternId: string,
    errorCluster: ErrorCluster,
    userChoice?: UserChoice,
    isFixAll?: boolean,
    fixAllSessionId?: string,
    preAnalysis?: ErrorAnalysisResult
  ): Promise<FixResult> => {
    // Start the async job
    const startResponse = await apiClient.post<{ job_id: string; status: string }>('/fix/start', {
      agent_id: agentId,
      pattern_id: patternId,
      error_cluster: errorCluster,
      user_choice: userChoice,
      is_fix_all: isFixAll ?? false,
      fix_all_session_id: fixAllSessionId,
      pre_analysis: preAnalysis,  // Pass pre-computed analysis to avoid redundant classification
    });
    
    const jobId = startResponse.data.job_id;
    
    // Poll for completion with exponential backoff
    // Start at 5s, increase to 15s max, total timeout ~10 minutes
    const maxAttempts = 60;
    const initialInterval = 5000;  // 5 seconds initially
    const maxInterval = 15000;     // 15 seconds max
    
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      // Exponential backoff: 5s, 7.5s, 11.25s, 15s (capped)
      const interval = Math.min(initialInterval * Math.pow(1.5, attempt), maxInterval);
      await new Promise(resolve => setTimeout(resolve, interval));
      
      const statusResponse = await apiClient.get(`/fix/job/${jobId}`);
      const jobStatus = statusResponse.data;
      
      if (jobStatus.status === 'completed' && jobStatus.result) {
        return jobStatus.result as FixResult;
      }
      
      if (jobStatus.status === 'failed') {
        throw new Error(jobStatus.error || 'Fix workflow failed');
      }
    }
    
    throw new Error('Fix workflow timed out after 10 minutes');
  },

  /**
   * Continue fix workflow with user choice
   */
  continueFixWorkflow: async (
    agentId: string,
    patternId: string,
    userChoice: UserChoice,
    previousResult: Record<string, unknown>
  ): Promise<FixResult> => {
    const response = await apiClient.post<FixResult>('/fix/continue', {
      agent_id: agentId,
      pattern_id: patternId,
      user_choice: userChoice,
      previous_result: previousResult,
    });
    return response.data;
  },

  /**
   * List deployed agents in Amazon Bedrock AgentCore
   */
  listDeployedAgents: async (region: string = 'us-east-1'): Promise<ListDeployedAgentsResult> => {
    const response = await apiClient.get<ListDeployedAgentsResult>('/agents/deployed', {
      params: { region },
    });
    return response.data;
  },

  /**
   * Test a prompt against a deployed agent in AWS
   */
  testDeployedAgent: async (
    agentArn: string,
    prompt: string,
    sessionId?: string
  ): Promise<TestDeployedAgentResult> => {
    const response = await apiClient.post<TestDeployedAgentResult>('/agents/test-deployed', {
      agent_arn: agentArn,
      prompt: prompt,
      session_id: sessionId,
    });
    return response.data;
  },
};
