/**
 * React hooks for AgentCore draft testing
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { testAgentApi } from '../api/testAgent';

/** One-click build + deploy draft */
export const useBuildAndTest = () => {
  return useMutation({
    mutationFn: ({ agentRuntimeId, agentName, workingDirectory }: {
      agentRuntimeId: string; agentName: string; workingDirectory: string;
    }) => testAgentApi.buildAndTest(agentRuntimeId, agentName, workingDirectory),
  });
};

/** Poll build progress */
export const useBuildStatus = (buildId: string | null, options?: { enabled?: boolean }) =>
  useQuery({
    queryKey: ['buildStatus', buildId],
    queryFn: () => testAgentApi.getBuildStatus(buildId!),
    enabled: options?.enabled !== false && !!buildId,
    refetchInterval: 3000, // Poll every 3 seconds
    staleTime: 0,
  });

/** Deploy fixed image as draft version (manual path — kept for direct ECR deploys) */
export const useDeployDraft = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ agentRuntimeId, imageUri }: { agentRuntimeId: string; imageUri: string }) =>
      testAgentApi.deployDraft(agentRuntimeId, imageUri),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['testAgentStatus', vars.agentRuntimeId] });
    },
  });
};

/** Invoke the test endpoint */
export const useInvokeTest = () =>
  useMutation({
    mutationFn: ({ agentRuntimeArn, prompt, sessionId }: {
      agentRuntimeArn: string; prompt: string; sessionId?: string;
    }) => testAgentApi.invokeTest(agentRuntimeArn, prompt, sessionId),
  });

/** Promote tested version to production */
export const usePromoteDraft = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (agentRuntimeId: string) => testAgentApi.promote(agentRuntimeId),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ['testAgentStatus', id] });
    },
  });
};

/** Discard draft */
export const useDiscardDraft = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (agentRuntimeId: string) => testAgentApi.discard(agentRuntimeId),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ['testAgentStatus', id] });
    },
  });
};

/** Poll test endpoint status */
export const useTestAgentStatus = (agentRuntimeId: string | null, options?: { enabled?: boolean }) =>
  useQuery({
    queryKey: ['testAgentStatus', agentRuntimeId],
    queryFn: () => testAgentApi.getStatus(agentRuntimeId!),
    enabled: options?.enabled !== false && !!agentRuntimeId,
    staleTime: 10000,
  });

/** Deploy (or update) the bundled sample agent — async, returns build_id to poll */
export const useDeploySample = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => testAgentApi.deploySample(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sampleStatus'] });
    },
  });
};

/** Poll whether the sample agent is deployed */
export const useSampleStatus = (options?: { enabled?: boolean }) =>
  useQuery({
    queryKey: ['sampleStatus'],
    queryFn: () => testAgentApi.getSampleStatus(),
    enabled: options?.enabled !== false,
    staleTime: 10000,
  });
