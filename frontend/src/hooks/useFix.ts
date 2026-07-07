/**
 * React hooks for fix operations
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fixApi, ErrorCluster, UserChoice, ErrorAnalysisResult } from '../api/fix';

/**
 * Hook to fetch error clusters for an agent
 * Cache key only uses agentId to avoid refetching on minor time changes
 */
export const useErrorClusters = (
  agentId: string,
  params?: {
    start_time?: string;
    end_time?: string;
    limit?: number;
    refresh?: boolean;
  },
  options?: { enabled?: boolean }
) => {
  return useQuery({
    queryKey: ['errorClusters', agentId, params?.start_time, params?.end_time],
    queryFn: () => fixApi.getErrorClusters(agentId, params),
    enabled: options?.enabled !== false && !!agentId,
    staleTime: 60000, // 1 minute - data is cached
    gcTime: 300000, // 5 minutes - keep in cache
    refetchOnWindowFocus: false, // Don't refetch on tab focus
  });
};

/**
 * Hook to analyze an error cluster
 */
export const useAnalyzeError = () => {
  return useMutation({
    mutationFn: ({ agentId, errorCluster }: { agentId: string; errorCluster: ErrorCluster }) =>
      fixApi.analyzeError(agentId, errorCluster),
  });
};

/**
 * Hook to start fix workflow
 * @param isFixAll - If true, use shared workspace (Fix All mode). If false, create separate workspace (Fix This).
 * @param fixAllSessionId - Unique session ID for Fix All workspace isolation
 * @param preAnalysis - Pre-computed analysis from analyzeError (avoids redundant classification - saves ~10s)
 */
export const useStartFixWorkflow = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      agentId,
      patternId,
      errorCluster,
      userChoice,
      isFixAll,
      fixAllSessionId,
      preAnalysis,
    }: {
      agentId: string;
      patternId: string;
      errorCluster: ErrorCluster;
      userChoice?: UserChoice;
      isFixAll?: boolean;
      fixAllSessionId?: string;
      preAnalysis?: ErrorAnalysisResult;
    }) => fixApi.startFixWorkflow(agentId, patternId, errorCluster, userChoice, isFixAll, fixAllSessionId, preAnalysis),
    onSuccess: (_, variables) => {
      // Invalidate error clusters to refresh status
      queryClient.invalidateQueries({ queryKey: ['errorClusters', variables.agentId] });
    },
  });
};

/**
 * Hook to continue fix workflow with user choice
 */
export const useContinueFixWorkflow = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      agentId,
      patternId,
      userChoice,
      previousResult,
    }: {
      agentId: string;
      patternId: string;
      userChoice: UserChoice;
      previousResult: Record<string, unknown>;
    }) => fixApi.continueFixWorkflow(agentId, patternId, userChoice, previousResult),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['errorClusters', variables.agentId] });
    },
  });
};

/**
 * Hook to list deployed agents in Amazon Bedrock AgentCore
 */
export const useListDeployedAgents = (region: string = 'us-east-1', options?: { enabled?: boolean }) => {
  return useQuery({
    queryKey: ['deployedAgents', region],
    queryFn: () => fixApi.listDeployedAgents(region),
    enabled: options?.enabled !== false,
    staleTime: 60000, // 1 minute
  });
};

/**
 * Hook to test a prompt against a deployed agent
 */
export const useTestDeployedAgent = () => {
  return useMutation({
    mutationFn: ({ agentArn, prompt, sessionId }: { agentArn: string; prompt: string; sessionId?: string }) =>
      fixApi.testDeployedAgent(agentArn, prompt, sessionId),
  });
};
