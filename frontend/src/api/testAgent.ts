/**
 * AgentCore Draft Testing API client
 */
import { apiClient } from './client';

export interface BuildAndTestResult {
  status: string;
  build_id: string;
  codebuild_id?: string;
  ecr_uri?: string;
  message: string;
  error?: string;
}

export interface BuildStatusResult {
  build_id: string;
  status: 'preparing' | 'packaging' | 'uploading' | 'building' | 'deploying' | 'ready' | 'failed' | 'not_found';
  message: string;
  ecr_uri: string;
  version: string;
  agent_runtime_id: string;
  agent_arn?: string;
  agent_name?: string;
  /** Draft pattern: version production still serves while the draft is validated */
  production_version?: string;
  /** 'draft' for fixes, 'sample' for the demo agent */
  deployed_as?: string;
  action?: string;
  error?: string;
}

export interface InvokeTestResult {
  status: string;
  prompt: string;
  response: string;
  session_id: string;
  qualifier: string;
  error?: string;
}

export interface PromoteResult {
  status: string;
  agent_runtime_id: string;
  promoted_version: string;
  production_endpoint?: string;
  message: string;
  error?: string;
}

export interface DiscardResult {
  status: string;
  message: string;
  error?: string;
}

export interface EndpointInfo {
  version: string | null;
  status: string | null;
}

export interface TestEndpointStatus {
  status: string;
  has_test_endpoint: boolean;
  test_endpoint: EndpointInfo | null;
  production_endpoint: EndpointInfo | null;
  default_endpoint?: EndpointInfo | null;
  error?: string;
}

export interface SampleDeployResult {
  status: string;
  build_id?: string;
  message: string;
  error?: string;
}

export interface SampleStatusResult {
  deployed: boolean;
  agent_id?: string;
  agent_arn?: string;
  agent_name?: string;
  status?: string;
}

export const testAgentApi = {
  /** One-click: build fixed code → ECR → deploy draft */
  buildAndTest: async (
    agentRuntimeId: string,
    agentName: string,
    workingDirectory: string,
  ): Promise<BuildAndTestResult> => {
    const resp = await apiClient.post<BuildAndTestResult>('/test-agent/build-and-test', {
      agent_runtime_id: agentRuntimeId,
      agent_name: agentName,
      working_directory: workingDirectory,
    });
    return resp.data;
  },

  /** Poll build progress */
  getBuildStatus: async (buildId: string): Promise<BuildStatusResult> => {
    const resp = await apiClient.get<BuildStatusResult>(`/test-agent/build-status/${buildId}`);
    return resp.data;
  },

  /** Deploy a pre-built image as draft (manual path) */
  deployDraft: async (agentRuntimeId: string, imageUri: string) => {
    const resp = await apiClient.post('/test-agent/deploy-draft', {
      agent_runtime_id: agentRuntimeId,
      image_uri: imageUri,
    });
    return resp.data;
  },

  /** Invoke the test endpoint with a prompt */
  invokeTest: async (agentRuntimeArn: string, prompt: string, sessionId?: string): Promise<InvokeTestResult> => {
    const resp = await apiClient.post<InvokeTestResult>('/test-agent/invoke', {
      agent_runtime_arn: agentRuntimeArn,
      prompt,
      session_id: sessionId,
    });
    return resp.data;
  },

  /** Promote tested version to production */
  promote: async (agentRuntimeId: string): Promise<PromoteResult> => {
    const resp = await apiClient.post<PromoteResult>('/test-agent/promote', {
      agent_runtime_id: agentRuntimeId,
    });
    return resp.data;
  },

  /** Discard draft */
  discard: async (agentRuntimeId: string): Promise<DiscardResult> => {
    const resp = await apiClient.post<DiscardResult>('/test-agent/discard', {
      agent_runtime_id: agentRuntimeId,
    });
    return resp.data;
  },

  /** Get test and production endpoint status */
  getStatus: async (agentRuntimeId: string): Promise<TestEndpointStatus> => {
    const resp = await apiClient.get<TestEndpointStatus>(`/test-agent/status/${agentRuntimeId}`);
    return resp.data;
  },

  /** Deploy (or update) the bundled sample/demo agent — async, returns build_id */
  deploySample: async (): Promise<SampleDeployResult> => {
    const resp = await apiClient.post<SampleDeployResult>('/test-agent/deploy-sample', {});
    return resp.data;
  },

  /** Check whether the sample agent is deployed and its status */
  getSampleStatus: async (): Promise<SampleStatusResult> => {
    const resp = await apiClient.get<SampleStatusResult>('/test-agent/sample-status');
    return resp.data;
  },
};
