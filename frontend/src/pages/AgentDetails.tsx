/**
 * Agent Details Page - Matches Streamlit dashboard layout
 */
import React, { useState, useCallback, useEffect } from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  CircularProgress,
  Alert,
  Button,
  LinearProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  RadioGroup,
  FormControlLabel,
  Radio,
  IconButton,
  Collapse,
  Tabs,
  Tab,
  Divider,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  ArrowBack,
  CheckCircle,
  Warning,
  Build,
  Refresh,
  Science,
  RocketLaunch,
} from '@mui/icons-material';
import { useParams, useNavigate } from 'react-router-dom';
import { useAgent, useAgentMetrics } from '../hooks/useAgents';
import { useErrorClusters, useStartFixWorkflow, useAnalyzeError } from '../hooks/useFix';
import { TimeRangeSelector, TimeRange, getTimeRangeFromPreset } from '../components/common/TimeRangeSelector';
import { ErrorCluster, FixResult, UserChoice, SuppressionSummary, fixApi, ErrorAnalysisResult } from '../api/fix';
import { useWorkflowStore } from '../stores/workflowStore';
import { useAuthStore } from '../stores/authStore';
import ReactMarkdown from 'react-markdown';

type PatternStatus = 'pending' | 'analyzing' | 'awaiting_choice' | 'processing' | 'fixed' | 'failed';

// Styled markdown container for fix results
const MarkdownContent: React.FC<{ content: string }> = ({ content }) => (
  <Box
    sx={{
      '& h1, & h2, & h3': { 
        fontSize: '1rem', 
        fontWeight: 600, 
        mt: 1.5, 
        mb: 1,
        color: 'text.primary',
        borderBottom: '1px solid #e0e0e0',
        pb: 0.5,
      },
      '& h2': { fontSize: '0.95rem' },
      '& h3': { fontSize: '0.9rem', borderBottom: 'none' },
      '& p': { fontSize: '0.85rem', mb: 1, lineHeight: 1.6 },
      '& ul, & ol': { pl: 2, mb: 1 },
      '& li': { fontSize: '0.85rem', mb: 0.5 },
      '& code': { 
        bgcolor: '#f5f5f5', 
        px: 0.5, 
        py: 0.25, 
        borderRadius: 0.5, 
        fontSize: '0.8rem',
        fontFamily: 'monospace',
      },
      '& pre': { 
        bgcolor: '#1e1e1e', 
        color: '#d4d4d4', 
        p: 1.5, 
        borderRadius: 1, 
        overflow: 'auto',
        fontSize: '0.75rem',
        '& code': { bgcolor: 'transparent', p: 0 },
      },
      '& strong, & b': { fontWeight: 600, color: 'text.primary' },
      '& hr': { my: 1.5, border: 'none', borderTop: '1px solid #e0e0e0' },
      '& blockquote': { 
        borderLeft: '3px solid #1976d2', 
        pl: 1.5, 
        ml: 0, 
        color: 'text.secondary',
        fontStyle: 'italic',
      },
    }}
  >
    <ReactMarkdown>{content}</ReactMarkdown>
  </Box>
);

interface PatternState {
  status: PatternStatus;
  classification?: { type: string; confidence: number; reasoning: string };
  fixResult?: FixResult;
  analysisResult?: ErrorAnalysisResult;  // Full analysis result for passing to startFixWorkflow (avoids redundant classification)
}

// Classification badge colors matching Streamlit
const classificationStyles: Record<string, { bg: string; label: string; icon: string }> = {
  code_fix_required: { bg: '#1f77b4', label: 'Code', icon: '🔧' },
  package_only: { bg: '#ff7f0e', label: 'Library', icon: '📦' },
  mixed: { bg: '#9467bd', label: 'Mixed', icon: '🔀' },
};

export const AgentDetails: React.FC = () => {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  
  const [patternStates, setPatternStates] = useState<Map<string, PatternState>>(new Map());
  const [fixingAll, setFixingAll] = useState(false);
  const [currentFixingPattern, setCurrentFixingPattern] = useState<string | null>(null);
  const [expandedPattern, setExpandedPattern] = useState<string | null>(null);
  
  const [choiceDialog, setChoiceDialog] = useState<{
    open: boolean;
    patternId: string;
    cluster: ErrorCluster | null;
  }>({ open: false, patternId: '', cluster: null });
  const [selectedChoice, setSelectedChoice] = useState<UserChoice>('code');
  
  // Global choice for Fix All - applies to all mixed patterns
  const [fixAllChoiceDialog, setFixAllChoiceDialog] = useState<{
    open: boolean;
    mixedCount: number;
    patternsToFix: ErrorCluster[];
  }>({ open: false, mixedCount: 0, patternsToFix: [] });
  const [globalMixedChoice, setGlobalMixedChoice] = useState<UserChoice>('both');
  
  const [activeTab, setActiveTab] = useState(0);
  const [timeRange, setTimeRange] = useState<TimeRange>(() => {
    const { startTime, endTime } = getTimeRangeFromPreset('24h');
    return { preset: '24h', startTime, endTime };
  });
  


  const { 
    setSelectedAgent, 
    setWorkingDirectory,
    setFixAllWorkingDirectory,
    workingDirectory,
    addFixedPattern, 
    fixedPatterns, 
    selectedAgentId: storedAgentId,
    inProgressFix,
    setInProgressFix,
    clearInProgressFix,
    wasFixAllOperation,
    setWasFixAllOperation,
  } = useWorkflowStore();
  const { hasRole } = useAuthStore();
  const canFix = hasRole('operator');
  const { data: agent, isLoading: agentLoading, error: agentError } = useAgent(agentId || '');
  const { data: metrics } = useAgentMetrics(agentId || '', timeRange.startTime, timeRange.endTime);
  const { data: clustersResponse, isLoading: clustersLoading, refetch: refetchClusters } = useErrorClusters(
    agentId || '',
    { 
      start_time: timeRange.startTime,
      end_time: timeRange.endTime,
      limit: 20 
    },
    { enabled: !!agentId }
  );
  
  // Extract clusters and suppression summary from response
  const errorClusters = clustersResponse?.clusters || [];
  const suppressionSummary = clustersResponse?.suppression_summary;

  const analyzeErrorMutation = useAnalyzeError();
  const startFixMutation = useStartFixWorkflow();

  useEffect(() => {
    if (agent && agentId) setSelectedAgent(agentId, agent.name);
  }, [agent, agentId, setSelectedAgent]);

  // Restore pattern states from fixedPatterns when returning to page
  // Track if we've restored fixed patterns (to prevent auto-classify from overwriting)
  const [hasRestoredPatterns, setHasRestoredPatterns] = useState(false);
  
  // Restore pattern states from fixedPatterns FIRST - before auto-classify runs
  // This runs whenever fixedPatterns changes or component mounts
  useEffect(() => {
    if (agentId && fixedPatterns.length > 0) {
      setPatternStates(prev => {
        const newMap = new Map(prev);
        fixedPatterns.forEach(fp => {
          // ALWAYS restore fixed patterns, overwriting any existing state
          // This ensures fixed patterns stay fixed when navigating back
          if (fp.fixResult) {
            newMap.set(fp.patternId, {
              status: 'fixed' as PatternStatus,
              fixResult: fp.fixResult as FixResult,
              // Restore classification from persisted store, fallback to current state
              classification: fp.classification || prev.get(fp.patternId)?.classification,
            });
          }
        });
        return newMap;
      });
      setHasRestoredPatterns(true);
    } else if (agentId) {
      // No fixed patterns to restore, allow auto-classify
      setHasRestoredPatterns(true);
    }
    // Reset restoration flag when agent changes
    if (agentId !== storedAgentId) {
      setHasRestoredPatterns(false);
    }
  }, [agentId, storedAgentId, fixedPatterns]);

  // Restore in-progress fix state on page load (survives refresh)
  // Note: This just shows the warning - it doesn't restart the fix
  useEffect(() => {
    if (inProgressFix && inProgressFix.agentId === agentId && agentId) {
      // A fix was in progress when page was refreshed - show processing state
      // The warning alert will be displayed to inform user
      setCurrentFixingPattern(inProgressFix.patternId);
      setPatternStates(prev => {
        const newMap = new Map(prev);
        newMap.set(inProgressFix.patternId, { 
          ...(newMap.get(inProgressFix.patternId) || { status: 'pending' as PatternStatus }), 
          status: 'processing' 
        });
        return newMap;
      });
    }
  }, [inProgressFix, agentId]);

  // Auto-classify all patterns when loaded - run sequentially to avoid race conditions
  // Use a ref to track which patterns have been queued for analysis
  const analyzedPatternsRef = React.useRef<Set<string>>(new Set());
  
  // Reset the ref when agent changes to allow re-analysis
  useEffect(() => {
    if (agentId) {
      analyzedPatternsRef.current = new Set();
    }
  }, [agentId]);
  
  // Auto-classify patterns when loaded - run SEQUENTIALLY to avoid race conditions
  // Only runs AFTER fixed patterns have been restored
  useEffect(() => {
    if (!hasRestoredPatterns) return; // Wait for restore to complete
    
    const classifyPatternsSequentially = async () => {
      if (!errorClusters || errorClusters.length === 0 || !agentId) return;
      
      for (const cluster of errorClusters) {
        // Skip if already analyzed or queued for analysis
        if (analyzedPatternsRef.current.has(cluster.pattern_id)) continue;
        
        const state = patternStates.get(cluster.pattern_id);
        // Skip if: already has classification, is analyzing, is fixed, or is processing
        const shouldSkip = state?.classification || 
                          state?.status === 'analyzing' || 
                          state?.status === 'fixed' || 
                          state?.status === 'processing';
        if (!shouldSkip) {
          analyzedPatternsRef.current.add(cluster.pattern_id);
          await analyzePattern(cluster);  // SEQUENTIAL - await each one to avoid race conditions
        }
      }
    };
    
    classifyPatternsSequentially();
  }, [errorClusters, agentId, hasRestoredPatterns]); // Depend on hasRestoredPatterns to wait for restore

  const updatePatternState = useCallback((patternId: string, updates: Partial<PatternState>) => {
    setPatternStates(prev => {
      const newMap = new Map(prev);
      newMap.set(patternId, { ...(newMap.get(patternId) || { status: 'pending' as PatternStatus }), ...updates });
      return newMap;
    });
  }, []);

  const analyzePattern = useCallback(async (cluster: ErrorCluster) => {
    if (!agentId) return null;
    const currentState = patternStates.get(cluster.pattern_id);
    if (currentState?.classification) return currentState.classification;
    
    // Debug: Log what we're sending
    console.log(`[CLASSIFY] Sending: pattern_id=${cluster.pattern_id}, error="${cluster.error_message.slice(0, 50)}..."`);
    
    updatePatternState(cluster.pattern_id, { status: 'analyzing' });
    try {
      const result = await analyzeErrorMutation.mutateAsync({ agentId, errorCluster: cluster });
      const classification = result.classification as PatternState['classification'];
      
      // Debug: Log what we received and where we're storing it
      console.log(`[CLASSIFY] Received for pattern_id=${cluster.pattern_id}: type=${classification?.type}, reasoning="${classification?.reasoning?.slice(0, 50)}..."`);
      
      // Store FULL analysis result to pass to startFixWorkflow (avoids redundant classification)
      updatePatternState(cluster.pattern_id, { status: 'pending', classification, analysisResult: result });
      return classification;
    } catch (error) {
      console.error(`[CLASSIFY] Error for pattern_id=${cluster.pattern_id}:`, error);
      updatePatternState(cluster.pattern_id, { status: 'pending' });
      return null;
    }
  }, [agentId, analyzeErrorMutation, updatePatternState, patternStates]);

  const handleFixPattern = useCallback(async (cluster: ErrorCluster, userChoice?: UserChoice, isPartOfFixAll?: boolean, fixAllSessionId?: string) => {
    if (!agentId) return;
    
    // Get current pattern state - use functional update to avoid stale closure
    const patternState = patternStates.get(cluster.pattern_id);
    
    // IMPORTANT: Capture classification BEFORE async call to avoid stale closure
    const capturedClassification = patternState?.classification;
    
    if (patternState?.classification?.type === 'mixed' && !userChoice) {
      setChoiceDialog({ open: true, patternId: cluster.pattern_id, cluster });
      return;
    }
    
    // IMPORTANT: Set both states synchronously before the async call
    // This ensures the UI updates immediately
    setCurrentFixingPattern(cluster.pattern_id);
    setPatternStates(prev => {
      const newMap = new Map(prev);
      newMap.set(cluster.pattern_id, { 
        ...(newMap.get(cluster.pattern_id) || { status: 'pending' as PatternStatus }), 
        status: 'processing' 
      });
      return newMap;
    });
    
    // Track in-progress fix in persisted store (survives page refresh)
    // Only set if not already in Fix All mode (Fix All sets its own tracking)
    const isInFixAll = isPartOfFixAll || inProgressFix?.isFixAll;
    
    // Get session ID from parameter or from inProgressFix
    const sessionId = fixAllSessionId || inProgressFix?.fixAllSessionId;
    
    if (!isInFixAll) {
      // This is an individual fix, reset the Fix All flag
      setWasFixAllOperation(false);
      setInProgressFix({
        patternId: cluster.pattern_id,
        agentId: agentId,
        startedAt: new Date().toISOString(),
        errorMessage: cluster.error_message,
      });
    }
    
    try {
      // Get pre-computed analysis to avoid redundant classification (saves ~10s)
      const preAnalysis = patternState?.analysisResult;
      
      const result = await startFixMutation.mutateAsync({
        agentId, 
        patternId: cluster.pattern_id, 
        errorCluster: cluster, 
        userChoice,
        isFixAll: isInFixAll,  // Pass to backend for shared/separate workspace decision
        fixAllSessionId: sessionId,  // Pass session ID for workspace isolation
        preAnalysis,  // Pass pre-computed analysis to skip redundant classification
      });

      if (result.status === 'awaiting_choice') {
        updatePatternState(cluster.pattern_id, { status: 'awaiting_choice', fixResult: result });
        setChoiceDialog({ open: true, patternId: cluster.pattern_id, cluster });
        if (!isInFixAll) clearInProgressFix();
        return;
      }

      if (result.status === 'fixed') {
        updatePatternState(cluster.pattern_id, { status: 'fixed', fixResult: result });
        if (result.working_directory) {
          setWorkingDirectory(result.working_directory);
          // For Fix All operations, also set the shared workspace
          if (isInFixAll) {
            setFixAllWorkingDirectory(result.working_directory);
          }
        }
        // Use captured classification (captured before async call to avoid stale closure)
        // Also derive classification from workflow_type if not available
        const derivedClassification = capturedClassification || {
          type: result.workflow_type || 'code_fix_required',
          confidence: 1.0,
          reasoning: `Fix completed with ${result.workflow_type || 'code'} workflow`,
        };
        addFixedPattern({
          patternId: cluster.pattern_id,
          errorMessage: cluster.error_message,
          fixedFiles: result.fixed_files,
          codeSummary: result.code_agent_summary,
          timestamp: new Date().toISOString(),
          // Store classification for restoring UI state when returning to page
          classification: derivedClassification,
          // Store full fixResult for restoring UI state when returning to page
          fixResult: {
            status: result.status,
            workflow_type: result.workflow_type,
            fixed_files: result.fixed_files,
            original_files: result.original_files,
            working_directory: result.working_directory,
            code_agent_summary: result.code_agent_summary,
            library_agent_output: result.library_agent_output,
            message: result.message,
          },
        });
      } else {
        updatePatternState(cluster.pattern_id, { status: 'failed', fixResult: result });
      }
    } catch {
      updatePatternState(cluster.pattern_id, { status: 'failed' });
    } finally {
      setCurrentFixingPattern(null);
      if (!isInFixAll) clearInProgressFix();
    }
  }, [agentId, startFixMutation, updatePatternState, setWorkingDirectory, setFixAllWorkingDirectory, addFixedPattern, setInProgressFix, clearInProgressFix, inProgressFix, setWasFixAllOperation]);
  // Note: patternStates removed from deps - we access it via closure but don't need to recreate callback when it changes

  // Queue for Fix All - stores patterns waiting to be processed after user makes choices
  const [fixAllQueue, setFixAllQueue] = useState<ErrorCluster[]>([]);
  const [fixAllInProgress, setFixAllInProgress] = useState(false);

  const handleUserChoice = async () => {
    const { cluster, patternId } = choiceDialog;
    setChoiceDialog({ open: false, patternId: '', cluster: null });
    
    if (cluster && selectedChoice !== 'skip') {
      await handleFixPattern(cluster, selectedChoice);
    } else if (selectedChoice === 'skip') {
      updatePatternState(patternId, { status: 'pending' });
    }
    
    // If Fix All is in progress, continue with remaining queue
    if (fixAllInProgress && fixAllQueue.length > 0) {
      const remainingQueue = fixAllQueue.slice(1);
      setFixAllQueue(remainingQueue);
      if (remainingQueue.length > 0) {
        await processFixAllQueue(remainingQueue);
      } else {
        setFixingAll(false);
        setFixAllInProgress(false);
      }
    }
  };

  const handleFixAllPatterns = async () => {
    if (!errorClusters || !agentId) return;
    
    // Build queue of patterns that need fixing
    // Include: pending, failed, analyzing (not yet classified), or no state
    // Exclude: fixed, processing, awaiting_choice
    const patternsToFix: ErrorCluster[] = [];
    for (const cluster of errorClusters) {
      const state = patternStates.get(cluster.pattern_id);
      const status = state?.status;
      // Include patterns that are not yet fixed or being processed
      if (!state || status === 'pending' || status === 'failed' || status === 'analyzing') {
        patternsToFix.push(cluster);
      }
    }
    
    if (patternsToFix.length === 0) return;
    
    // Count mixed patterns (only those with classification already done)
    const mixedPatterns = patternsToFix.filter(cluster => {
      const state = patternStates.get(cluster.pattern_id);
      return state?.classification?.type === 'mixed';
    });
    
    // Only show choice dialog if there are MIXED patterns
    // If all patterns are code-only, library-only, or still analyzing, proceed directly
    if (mixedPatterns.length > 0) {
      setFixAllChoiceDialog({
        open: true,
        mixedCount: mixedPatterns.length,
        patternsToFix,
      });
    } else {
      // No mixed patterns - start fixing immediately without asking user
      await startFixAllExecution(patternsToFix);
    }
  };
  
  // Start Fix All execution after choice is made
  const startFixAllExecution = async (patternsToFix: ErrorCluster[]) => {
    if (!agentId) return;
    
    // Generate unique session ID for this Fix All operation
    const sessionId = `fixall_${Date.now().toString(36)}_${crypto.randomUUID().slice(0, 8)}`;
    
    setWasFixAllOperation(true); // Mark that this is a Fix All operation
    setFixingAll(true);
    setFixAllInProgress(true);
    
    // Track Fix All in persisted store (including session ID)
    setInProgressFix({
      patternId: patternsToFix[0].pattern_id,
      agentId: agentId,
      startedAt: new Date().toISOString(),
      errorMessage: `Fix All: ${patternsToFix.length} patterns`,
      isFixAll: true,
      fixAllTotal: patternsToFix.length,
      fixAllCompleted: 0,
      fixAllSessionId: sessionId,
    });
    
    setFixAllQueue(patternsToFix);
    await processFixAllQueue(patternsToFix, sessionId);
  };
  
  // Handle global choice for Fix All
  const handleFixAllWithChoice = async () => {
    const { patternsToFix } = fixAllChoiceDialog;
    setFixAllChoiceDialog({ open: false, mixedCount: 0, patternsToFix: [] });
    
    if (globalMixedChoice === 'skip') {
      // Skip all mixed patterns - only fix non-mixed ones
      const nonMixedPatterns = patternsToFix.filter(cluster => {
        const state = patternStates.get(cluster.pattern_id);
        return state?.classification?.type !== 'mixed';
      });
      if (nonMixedPatterns.length > 0) {
        await startFixAllExecution(nonMixedPatterns);
      }
    } else {
      await startFixAllExecution(patternsToFix);
    }
  };

  const processFixAllQueue = async (queue: ErrorCluster[], sessionId?: string) => {
    for (let i = 0; i < queue.length; i++) {
      const cluster = queue[i];
      const state = patternStates.get(cluster.pattern_id);
      
      // Skip if already fixed
      if (state?.status === 'fixed') {
        if (inProgressFix?.isFixAll) {
          setInProgressFix({
            ...inProgressFix,
            fixAllCompleted: (inProgressFix.fixAllCompleted || 0) + 1,
          });
        }
        continue;
      }
      
      // Update current pattern in progress tracking
      if (inProgressFix?.isFixAll && agentId) {
        setInProgressFix({
          ...inProgressFix,
          patternId: cluster.pattern_id,
          fixAllCompleted: i,
        });
      }
      
      // Get or compute classification
      const classification = state?.classification || await analyzePattern(cluster);
      
      // If mixed, use the global choice that was selected upfront
      if (classification?.type === 'mixed') {
        await handleFixPattern(cluster, globalMixedChoice, true, sessionId); // true = part of Fix All
      } else {
        // For non-mixed, proceed directly
        await handleFixPattern(cluster, undefined, true, sessionId); // true = part of Fix All
      }
    }
    
    // All done - wasFixAllOperation stays true so Next Steps don't show on individual cards
    setFixingAll(false);
    setFixAllInProgress(false);
    setFixAllQueue([]);
    clearInProgressFix();
  };

  if (agentLoading) return <Box display="flex" justifyContent="center" p={4}><CircularProgress /></Box>;
  if (agentError || !agent) return (
    <Box p={2}>
      <Alert severity="error">Failed to load agent. {agentError?.message}</Alert>
      <Button startIcon={<ArrowBack />} onClick={() => navigate('/agents')} sx={{ mt: 1 }}>Back</Button>
    </Box>
  );

  const fixedCount = errorClusters?.filter(c => patternStates.get(c.pattern_id)?.status === 'fixed').length || 0;
  const totalCount = errorClusters?.length || 0;

  return (
    <Box sx={{ p: 2, maxWidth: 1200 }}>
      {/* Header Row - Left aligned */}
      <Box display="flex" alignItems="center" gap={2} mb={1}>
        <IconButton size="small" onClick={() => navigate('/agents')}><ArrowBack /></IconButton>
        <Typography variant="h5" fontWeight={600}>{agent.name}</Typography>
        <Chip
          size="small"
          icon={agent.status === 'ACTIVE' ? <CheckCircle /> : <Warning />}
          label={agent.status}
          color={agent.status === 'ACTIVE' ? 'success' : 'warning'}
        />
        <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 1 }}>
          <TimeRangeSelector value={timeRange} onChange={setTimeRange} showCustom={true} />
          <IconButton size="small" onClick={async () => {
            // Force refresh from backend (bypass cache)
            if (agentId) {
              await fixApi.getErrorClusters(agentId, {
                start_time: timeRange.startTime,
                end_time: timeRange.endTime,
                limit: 20,
                refresh: true,
              });
            }
            refetchClusters();
          }}><Refresh /></IconButton>
        </Box>
      </Box>

      {/* Metrics Row - Left aligned like Streamlit */}
      {metrics && (() => {
        // Calculate actual errors from error clusters (more accurate than CloudWatch metrics)
        const totalErrorOccurrences = errorClusters?.reduce((sum, c) => sum + c.count, 0) || 0;
        const actualErrors = Math.max(metrics.runtime_errors || 0, totalErrorOccurrences);
        const invocations = metrics.runtime_invocations || 0;
        const actualErrorRate = invocations > 0 ? (actualErrors / invocations) * 100 : 0;
        
        return (
          <Box display="flex" gap={3} mb={2} sx={{ fontSize: 14, color: 'text.secondary' }}>
            <span>📊 <b style={{ color: '#1976d2' }}>{invocations}</b> invocations</span>
            <span>❌ <b style={{ color: actualErrors > 0 ? '#d32f2f' : 'inherit' }}>{actualErrors}</b> errors</span>
            <span>⚡ <b style={{ color: actualErrorRate > 0 ? '#d32f2f' : 'inherit' }}>{actualErrorRate.toFixed(1)}%</b> error rate</span>
            <span>⏱️ <b>{(metrics.avg_duration_seconds || 0).toFixed(2)}s</b> avg</span>
          </Box>
        );
      })()}

      {/* Tabs - Observability and Errors like Streamlit */}
      <Paper sx={{ mb: 2 }}>
        <Tabs 
          value={activeTab} 
          onChange={(_, newValue) => setActiveTab(newValue)}
          sx={{ borderBottom: 1, borderColor: 'divider' }}
        >
          <Tab label="🔭 Observability" />
          <Tab label={`🚨 Errors ${errorClusters?.length ? `(${errorClusters.length})` : ''}`} />
        </Tabs>
      </Paper>

      {/* Observability Tab */}
      {activeTab === 0 && (
        <Paper sx={{ p: 2, mb: 2 }}>
          <Typography variant="h6" fontWeight={600} gutterBottom>
            🔭 Comprehensive Observability (ADOT)
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" mb={2}>
            Real-time metrics from AWS Distro for OpenTelemetry (ADOT) - CloudWatch Logs
          </Typography>

          {!metrics ? (
            <Box display="flex" justifyContent="center" p={4}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              {/* Calculate actual error count from error clusters (more accurate than CloudWatch metrics) */}
              {(() => {
                const totalErrorOccurrences = errorClusters?.reduce((sum, c) => sum + c.count, 0) || 0;
                const errorPatternCount = errorClusters?.length || 0;
                const actualErrors = Math.max(metrics.runtime_errors || 0, totalErrorOccurrences);
                const invocations = metrics.runtime_invocations || 0;
                const actualErrorRate = invocations > 0 ? (actualErrors / invocations) * 100 : 0;
                const hasErrors = actualErrors > 0 || errorPatternCount > 0;

                return (
                  <>
                    {/* Runtime Metrics Section */}
                    <Typography variant="h6" fontWeight={600} gutterBottom sx={{ mt: 2, fontSize: '1.1rem' }}>
                      📈 Runtime Metrics (AWS Console Format)
                    </Typography>
                    <Box display="grid" gridTemplateColumns="repeat(4, 1fr)" gap={2} mb={3}>
                      <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#f5f5f5', borderRadius: 1 }}>
                        <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Runtime Sessions</Typography>
                        <Typography variant="h4" fontWeight={600}>{metrics.runtime_sessions || 0}</Typography>
                      </Paper>
                      <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#f5f5f5', borderRadius: 1 }}>
                        <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Runtime Invocations</Typography>
                        <Typography variant="h4" fontWeight={600} color="primary.main">{invocations}</Typography>
                      </Paper>
                      <Paper elevation={0} sx={{ p: 2.5, bgcolor: hasErrors ? '#ffebee' : '#f5f5f5', borderRadius: 1 }}>
                        <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Error Rate (from logs)</Typography>
                        <Typography variant="h4" fontWeight={600} color={hasErrors ? 'error.main' : 'text.primary'}>
                          {actualErrorRate.toFixed(1)}%
                        </Typography>
                        <Typography variant="body2" color="error.main">
                          {actualErrors} errors ({errorPatternCount} patterns)
                        </Typography>
                      </Paper>
                      <Paper elevation={0} sx={{ p: 2.5, bgcolor: metrics.runtime_throttle_rate > 0 ? '#fff3e0' : '#f5f5f5', borderRadius: 1 }}>
                        <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Runtime Throttle Rate</Typography>
                        <Typography variant="h4" fontWeight={600} color={metrics.runtime_throttle_rate > 0 ? 'warning.main' : 'text.primary'}>
                          {(metrics.runtime_throttle_rate || 0).toFixed(1)}%
                        </Typography>
                        <Typography variant="body2" color="warning.main">{metrics.runtime_throttles || 0} throttles</Typography>
                      </Paper>
                    </Box>

              <Divider sx={{ my: 2 }} />

              {/* Resource Consumption Section */}
              <Typography variant="h6" fontWeight={600} gutterBottom sx={{ fontSize: '1.1rem' }}>
                💰 Resource Consumption
              </Typography>
              <Box display="grid" gridTemplateColumns="repeat(2, 1fr)" gap={2} mb={3}>
                <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#e3f2fd', borderRadius: 1 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>vCPU Consumption</Typography>
                  <Typography variant="h4" fontWeight={600}>{(metrics.vcpu_consumption_hours || 0).toFixed(2)} vCPU-hrs</Typography>
                </Paper>
                <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#e8f5e9', borderRadius: 1 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Memory Consumption</Typography>
                  <Typography variant="h4" fontWeight={600}>{(metrics.memory_consumption_gb_hours || 0).toFixed(2)} GB-hrs</Typography>
                </Paper>
              </Box>

              <Divider sx={{ my: 2 }} />

              {/* Performance Metrics Section */}
              <Typography variant="h6" fontWeight={600} gutterBottom sx={{ fontSize: '1.1rem' }}>
                ⚡ Performance Metrics
              </Typography>
              <Box display="grid" gridTemplateColumns="repeat(3, 1fr)" gap={2} mb={3}>
                <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#f5f5f5', borderRadius: 1 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Average Duration</Typography>
                  <Typography variant="h4" fontWeight={600}>{(metrics.avg_duration_seconds || 0).toFixed(2)}s</Typography>
                </Paper>
                <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#ffebee', borderRadius: 1 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Max Duration</Typography>
                  <Typography variant="h4" fontWeight={600} color="error.main">{(metrics.max_duration_seconds || 0).toFixed(2)}s</Typography>
                </Paper>
                <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#e8f5e9', borderRadius: 1 }}>
                  <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Min Duration</Typography>
                  <Typography variant="h4" fontWeight={600} color="success.main">{(metrics.min_duration_seconds || 0).toFixed(2)}s</Typography>
                </Paper>
              </Box>

              {/* Detailed Breakdown Section - Collapsible */}
              <Accordion defaultExpanded={false} sx={{ mt: 2, bgcolor: '#fafafa', '&:before': { display: 'none' } }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="subtitle1" fontWeight={600}>
                    📊 Detailed Breakdown
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Box display="grid" gridTemplateColumns="repeat(2, 1fr)" gap={2}>
                    <Paper elevation={0} sx={{ p: 2, bgcolor: '#f5f5f5', borderRadius: 1 }}>
                      <Typography variant="subtitle1" fontWeight={600} gutterBottom sx={{ fontSize: '1rem' }}>Invocation Summary</Typography>
                      <Box display="flex" flexDirection="column" gap={1}>
                        <Typography variant="body1" sx={{ fontSize: '0.95rem' }}>• Total Invocations: <b>{invocations}</b></Typography>
                        <Typography variant="body1" sx={{ fontSize: '0.95rem' }}>• Unique Sessions: <b>{metrics.runtime_sessions || 0}</b></Typography>
                        <Typography variant="body1" sx={{ fontSize: '0.95rem' }}>• Errors (from logs): <b style={{ color: '#d32f2f' }}>{actualErrors}</b></Typography>
                        <Typography variant="body1" sx={{ fontSize: '0.95rem' }}>• Error Patterns: <b style={{ color: '#d32f2f' }}>{errorPatternCount}</b></Typography>
                        <Typography variant="body1" sx={{ fontSize: '0.95rem' }}>• Faults: <b style={{ color: '#ed6c02' }}>{metrics.runtime_faults || 0}</b></Typography>
                        <Typography variant="body1" sx={{ fontSize: '0.95rem' }}>• Throttles: <b style={{ color: '#ed6c02' }}>{metrics.runtime_throttles || 0}</b></Typography>
                      </Box>
                    </Paper>
                    <Paper elevation={0} sx={{ p: 2.5, bgcolor: '#f5f5f5', borderRadius: 1 }}>
                      <Typography variant="subtitle1" fontWeight={600} gutterBottom sx={{ fontSize: '1rem' }}>Success Rate</Typography>
                      {invocations > 0 ? (
                        <>
                          {(() => {
                            const successCount = Math.max(0, invocations - actualErrors - (metrics.runtime_faults || 0));
                            const successRate = (successCount / invocations) * 100;
                            const color = successRate >= 95 ? '#2e7d32' : successRate >= 80 ? '#ed6c02' : '#d32f2f';
                            return (
                              <Box>
                                <Typography variant="h3" fontWeight={700} color={color}>
                                  {successRate.toFixed(1)}%
                                </Typography>
                                <LinearProgress 
                                  variant="determinate" 
                                  value={Math.max(0, successRate)} 
                                  sx={{ 
                                    mt: 1, 
                                    height: 10, 
                                    borderRadius: 5,
                                    bgcolor: '#e0e0e0',
                                    '& .MuiLinearProgress-bar': { bgcolor: color }
                                  }} 
                                />
                                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                                  {successCount} successful / {invocations} total
                                </Typography>
                              </Box>
                            );
                          })()}
                        </>
                      ) : (
                        <Typography variant="body2" color="text.secondary">No invocations yet</Typography>
                      )}
                    </Paper>
                  </Box>
                </AccordionDetails>
              </Accordion>

              {/* No data message */}
              {invocations === 0 && (
                <Alert severity="info" sx={{ mt: 2 }}>
                  No invocations found in the selected time range. Try extending the time range or invoking the agent.
                </Alert>
              )}
                  </>
                );
              })()}
            </>
          )}
        </Paper>
      )}

      {/* Error Patterns Tab */}
      {activeTab === 1 && (
      <Paper sx={{ p: 2 }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h6" fontWeight={600}>
            📊 Error Patterns
            {totalCount > 0 && <Chip size="small" label={`${fixedCount}/${totalCount}`} sx={{ ml: 1 }} color={fixedCount === totalCount ? 'success' : 'default'} />}
          </Typography>
          {totalCount > 0 && (
            <Button
              variant="contained"
              size="small"
              startIcon={fixingAll ? <CircularProgress size={14} color="inherit" /> : <Build />}
              onClick={handleFixAllPatterns}
              disabled={fixingAll || fixedCount === totalCount || !canFix}
            >
              {fixingAll ? 'Fixing...' : fixedCount === totalCount ? '✅ All Fixed' : `Fix All (${totalCount - fixedCount})`}
            </Button>
          )}
        </Box>
        
        {/* Suppression Summary - shows deduplication stats (only when there are clusters) */}
        {suppressionSummary && suppressionSummary.total_original_errors > 0 && errorClusters.length > 0 && (
          <Box sx={{ mb: 2, p: 2.5, bgcolor: '#f5f5f5', borderRadius: 1, border: '1px solid #e0e0e0' }}>
            <Box display="flex" gap={4} flexWrap="wrap" alignItems="center">
              <Box>
                <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Total Errors</Typography>
                <Typography variant="h4" fontWeight={600}>{suppressionSummary.total_original_errors}</Typography>
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Unique Patterns</Typography>
                <Typography variant="h4" fontWeight={600} color="primary.main">{suppressionSummary.total_unique_patterns}</Typography>
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Deduplicated</Typography>
                <Typography variant="h4" fontWeight={600} color="success.main">{suppressionSummary.total_suppressed}</Typography>
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.9rem' }}>Dedup Rate</Typography>
                <Typography variant="h4" fontWeight={600}>{suppressionSummary.suppression_rate.toFixed(1)}%</Typography>
              </Box>
            </Box>
            {suppressionSummary.top_suppressed_errors.length > 0 && (
              <Box sx={{ mt: 2, pt: 2, borderTop: '1px solid #e0e0e0' }}>
                <Typography variant="body2" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                  Top Deduplicated Errors:
                </Typography>
                {suppressionSummary.top_suppressed_errors.slice(0, 3).map((err, i) => (
                  <Typography key={i} variant="body1" sx={{ fontSize: '0.9rem', color: 'text.secondary' }}>
                    • {err.message.slice(0, 60)}... ({err.original_count} occurrences → 1 pattern)
                  </Typography>
                ))}
              </Box>
            )}
          </Box>
        )}
        
        {/* In-Progress Fix Warning (only shows for stale/orphaned fixes after page refresh) */}
        {inProgressFix && inProgressFix.agentId === agentId && !fixingAll && !currentFixingPattern && (
          <Alert 
            severity="warning" 
            sx={{ mb: 2 }}
            action={
              <Button 
                color="inherit" 
                size="small" 
                onClick={() => {
                  clearInProgressFix();
                  setCurrentFixingPattern(null);
                  updatePatternState(inProgressFix.patternId, { status: 'pending' });
                }}
              >
                Dismiss
              </Button>
            }
          >
            <Typography variant="body2">
              {inProgressFix.isFixAll ? (
                <>
                  <strong>Fix All in progress:</strong> Started at {new Date(inProgressFix.startedAt).toLocaleTimeString()} 
                  ({inProgressFix.fixAllCompleted || 0}/{inProgressFix.fixAllTotal || 0} patterns completed).
                  The operation may still be running in the backend. Refresh the page to see results.
                </>
              ) : (
                <>
                  <strong>Fix in progress:</strong> A fix operation was started at {new Date(inProgressFix.startedAt).toLocaleTimeString()} 
                  and may still be running in the backend. If the fix completes, refresh the page to see results.
                </>
              )}
            </Typography>
          </Alert>
        )}

        {/* Single Fix Progress Panel */}
        {currentFixingPattern && !fixingAll && (
          <Box sx={{ mb: 2, p: 2, bgcolor: '#e3f2fd', borderRadius: 1, border: '1px solid #90caf9' }}>
            <Box display="flex" alignItems="center" gap={1} mb={1}>
              <CircularProgress size={18} />
              <Typography variant="subtitle2" fontWeight={600} color="primary.main">
                🔄 Fix in Progress
              </Typography>
            </Box>
            <LinearProgress sx={{ mb: 1, borderRadius: 1, height: 8 }} />
            <Typography variant="body2" color="text.secondary">
              Analyzing error pattern and generating fix... This may take 1-3 minutes.
            </Typography>
          </Box>
        )}

        {/* Fix All Progress Panel */}
        {fixingAll && (
          <Box sx={{ mb: 2, p: 2, bgcolor: '#e3f2fd', borderRadius: 1, border: '1px solid #90caf9' }}>
            <Box display="flex" alignItems="center" gap={1} mb={1}>
              <CircularProgress size={18} />
              <Typography variant="subtitle2" fontWeight={600} color="primary.main">
                🔄 Fixing All Patterns ({fixedCount}/{totalCount})
              </Typography>
            </Box>
            <LinearProgress 
              variant="determinate" 
              value={(fixedCount / totalCount) * 100} 
              sx={{ mb: 1, borderRadius: 1, height: 8 }} 
            />
            <Typography variant="body2" color="text.secondary">
              {currentFixingPattern ? `Currently fixing pattern: ${currentFixingPattern.slice(0, 20)}...` : 'Processing...'}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
              ⏱️ This may take 3-5 minutes. Please wait...
            </Typography>
          </Box>
        )}

        {clustersLoading ? (
          <Box display="flex" justifyContent="center" p={2}><CircularProgress size={24} /></Box>
        ) : !errorClusters?.length ? (
          <Alert severity="success" sx={{ py: 1 }}>No errors found in the selected time range ({timeRange.preset || 'custom'}) 🎉</Alert>
        ) : (
          <Box display="flex" flexDirection="column" gap={2}>
            {errorClusters.map((cluster, idx) => {
              const state = patternStates.get(cluster.pattern_id);
              const status = state?.status || 'pending';
              const classification = state?.classification;
              const isExpanded = expandedPattern === cluster.pattern_id;
              const isFixing = currentFixingPattern === cluster.pattern_id;
              const classStyle = classification?.type ? classificationStyles[classification.type] : null;
              const confidence = classification?.confidence ? Math.round(classification.confidence * 100) : 0;

              // Status styling
              const statusConfig = {
                fixed: { bg: '#2e7d32', icon: '✅', text: 'Fixed' },
                processing: { bg: '#1976d2', icon: '🔄', text: 'Processing' },
                analyzing: { bg: '#1976d2', icon: '🔄', text: 'Analyzing' },
                failed: { bg: '#d32f2f', icon: '❌', text: 'Failed' },
                pending: { bg: '#ed6c02', icon: '⏳', text: 'Pending' },
                awaiting_choice: { bg: '#9c27b0', icon: '❓', text: 'Choose' },
              }[status] || { bg: 'gray', icon: '?', text: status };

              return (
                <Paper
                  key={cluster.pattern_id}
                  elevation={1}
                  sx={{ 
                    p: 2, 
                    borderLeft: `5px solid ${status === 'fixed' ? '#2e7d32' : status === 'failed' ? '#d32f2f' : '#1976d2'}`,
                    '&:hover': { boxShadow: 3 }
                  }}
                >
                  {/* Row 1: Error Header with colored background */}
                  <Box 
                    sx={{ 
                      p: 1.5, 
                      mb: 2, 
                      borderRadius: 1,
                      bgcolor: cluster.error_type.includes('Error') ? '#ffebee' : '#fff3e0'
                    }}
                  >
                    <Typography variant="subtitle1" fontWeight={600} color={cluster.error_type.includes('Error') ? 'error.main' : 'warning.main'}>
                      🔴 #{idx + 1} {cluster.error_type}: {cluster.error_message.slice(0, 80)}{cluster.error_message.length > 80 ? '...' : ''}
                    </Typography>
                  </Box>

                  {/* Row 2: Classification, Status, Count, Actions */}
                  <Box display="flex" alignItems="center" gap={2} flexWrap="wrap" mb={1}>
                    {/* Classification Badge */}
                    <Box>
                      {classification ? (
                        <Box
                          sx={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            px: 1.5,
                            py: 0.75,
                            borderRadius: 1,
                            bgcolor: classStyle?.bg || '#666',
                            color: 'white',
                            fontSize: 12,
                            fontWeight: 500,
                          }}
                          title={classification.reasoning}
                        >
                          {classStyle?.icon} {classStyle?.label} ({confidence}%)
                        </Box>
                      ) : status === 'analyzing' ? (
                        <Box display="flex" alignItems="center" gap={1}>
                          <CircularProgress size={16} />
                          <Typography variant="caption">Classifying...</Typography>
                        </Box>
                      ) : (
                        <Typography variant="caption" color="text.secondary">Classification pending</Typography>
                      )}
                    </Box>

                    {/* Status Badge */}
                    <Box
                      sx={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        px: 1.5,
                        py: 0.75,
                        borderRadius: 1,
                        bgcolor: statusConfig.bg,
                        color: 'white',
                        fontSize: 12,
                      }}
                    >
                      {statusConfig.icon} {statusConfig.text}
                    </Box>

                    {/* Count */}
                    <Box sx={{ px: 1.5, py: 0.5, bgcolor: 'grey.100', borderRadius: 1 }}>
                      <Typography variant="body2"><b>{cluster.count}</b> occurrences</Typography>
                    </Box>

                    {/* Spacer */}
                    <Box flex={1} />

                    {/* Actions */}
                    <Button
                      variant="outlined"
                      size="small"
                      onClick={() => setExpandedPattern(isExpanded ? null : cluster.pattern_id)}
                      sx={{ mr: 1 }}
                    >
                      {isExpanded ? '▲ Hide Details' : '▼ View Details'}
                    </Button>
                    <Button
                      variant={status === 'fixed' ? 'outlined' : 'contained'}
                      color={status === 'fixed' ? 'success' : status === 'failed' ? 'error' : 'primary'}
                      size="small"
                      startIcon={isFixing || status === 'processing' ? <CircularProgress size={14} color="inherit" /> : <Build />}
                      onClick={() => handleFixPattern(cluster)}
                      disabled={!!currentFixingPattern || status === 'analyzing' || status === 'processing' || status === 'fixed' || !canFix}
                    >
                      {status === 'fixed' ? 'Fixed ✓' : status === 'failed' ? 'Retry' : isFixing ? 'Fixing...' : 'Fix This'}
                    </Button>
                  </Box>

                  {/* Row 3: AI Reasoning Preview (always visible if available) */}
                  {classification?.reasoning && (
                    <Box sx={{ mt: 1.5, p: 1.5, bgcolor: '#e3f2fd', borderRadius: 1, border: '1px solid #90caf9' }}>
                      <Typography variant="body2">
                        💭 <b>AI Analysis:</b> {classification.reasoning}
                      </Typography>
                    </Box>
                  )}

                  {/* Fix Result Panel - Shows only when completed or failed (progress shown in global panel) */}
                  {(status === 'fixed' || status === 'failed') && (
                    <Box 
                      sx={{ 
                        mt: 2, 
                        p: 2, 
                        borderRadius: 1,
                        bgcolor: status === 'fixed' ? '#e8f5e9' : '#ffebee',
                        border: `1px solid ${status === 'fixed' ? '#a5d6a7' : '#ef9a9a'}`,
                      }}
                    >
                      <Box display="flex" alignItems="center" gap={1} mb={1}>
                        <Typography variant="subtitle2" fontWeight={600} color={status === 'fixed' ? 'success.main' : 'error.main'}>
                          {status === 'fixed' ? '✅ Fix Completed' : '❌ Fix Failed'}
                        </Typography>
                      </Box>
                      
                      {status === 'fixed' && state?.fixResult && (
                        <Box>
                          {/* Workflow Type Badge */}
                          {state.fixResult.workflow_type && (
                            <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Chip 
                                size="small"
                                label={
                                  state.fixResult.workflow_type === 'mixed' ? '🔀 Multi-Agent Workflow' :
                                  state.fixResult.workflow_type === 'package_only' ? '📦 Library Fix' :
                                  '🔧 Code Fix'
                                }
                                sx={{ 
                                  bgcolor: state.fixResult.workflow_type === 'mixed' ? '#9467bd' :
                                           state.fixResult.workflow_type === 'package_only' ? '#ff7f0e' : '#1f77b4',
                                  color: 'white',
                                  fontWeight: 600,
                                }}
                              />
                              {state.fixResult.workflow_type === 'mixed' && (
                                <Typography variant="caption" color="text.secondary">
                                  Both Library Agent and Code Agent were used
                                </Typography>
                              )}
                            </Box>
                          )}

                          {/* For Mixed Workflow: Show Library Agent Analysis first */}
                          {state.fixResult.workflow_type === 'mixed' && state.fixResult.library_agent_output && (
                            <Accordion defaultExpanded sx={{ mb: 2, bgcolor: 'white', border: '1px solid #ff7f0e', '&:before': { display: 'none' } }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: '#fff3e0' }}>
                                <Typography variant="subtitle2" fontWeight={600} sx={{ color: '#e65100' }}>
                                  📚 Library Agent Analysis
                                </Typography>
                              </AccordionSummary>
                              <AccordionDetails sx={{ pt: 0, maxHeight: 500, overflow: 'auto' }}>
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                                  📌 Package and dependency recommendations from the Library Agent
                                </Typography>
                                <MarkdownContent content={state.fixResult.library_agent_output} />
                              </AccordionDetails>
                            </Accordion>
                          )}

                          {/* Code Agent Summary - Different display based on workflow type */}
                          {state.fixResult.code_agent_summary && (
                            state.fixResult.workflow_type === 'mixed' ? (
                              <Accordion defaultExpanded sx={{ mb: 2, bgcolor: 'white', border: '1px solid #1f77b4', '&:before': { display: 'none' } }}>
                                <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ bgcolor: '#e3f2fd' }}>
                                  <Typography variant="subtitle2" fontWeight={600} color="primary.main">
                                    🔧 Code Agent - Comprehensive Summary
                                  </Typography>
                                </AccordionSummary>
                                <AccordionDetails sx={{ pt: 0 }}>
                                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                                    📌 AI-generated summary of all code fixes applied by the Code Agent
                                  </Typography>
                                  <MarkdownContent content={state.fixResult.code_agent_summary} />
                                </AccordionDetails>
                              </Accordion>
                            ) : (
                              <Accordion defaultExpanded sx={{ mb: 2, bgcolor: 'white', border: '1px solid #a5d6a7', '&:before': { display: 'none' } }}>
                                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                  <Typography variant="subtitle2" fontWeight={600} color="success.main">📝 Fix Summary</Typography>
                                </AccordionSummary>
                                <AccordionDetails sx={{ pt: 0 }}>
                                  <MarkdownContent content={state.fixResult.code_agent_summary} />
                                </AccordionDetails>
                              </Accordion>
                            )
                          )}

                          {/* For non-mixed workflows: Show Library Agent Output if available */}
                          {state.fixResult.workflow_type !== 'mixed' && state.fixResult.library_agent_output && (
                            <Accordion defaultExpanded={false} sx={{ mb: 2, bgcolor: 'white', border: '1px solid #e0e0e0', '&:before': { display: 'none' } }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Typography variant="subtitle2" fontWeight={600}>📚 Library Agent Analysis</Typography>
                              </AccordionSummary>
                              <AccordionDetails sx={{ pt: 0, maxHeight: 400, overflow: 'auto' }}>
                                <MarkdownContent content={state.fixResult.library_agent_output} />
                              </AccordionDetails>
                            </Accordion>
                          )}

                          {/* Fixed Files with Diff View */}
                          {state.fixResult.fixed_files && Object.keys(state.fixResult.fixed_files).length > 0 ? (
                            <Accordion defaultExpanded sx={{ mb: 2, bgcolor: 'white', border: '1px solid #4caf50', '&:before': { display: 'none' } }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                                  <Typography variant="subtitle2" fontWeight={600}>
                                    🔧 Fixed Files ({Object.keys(state.fixResult.fixed_files).length})
                                  </Typography>
                                  {Object.keys(state.fixResult.fixed_files).map((file, i) => (
                                    <Chip key={i} size="small" label={`📄 ${file}`} sx={{ fontFamily: 'monospace', fontSize: 11 }} />
                                  ))}
                                </Box>
                              </AccordionSummary>
                              <AccordionDetails sx={{ p: 0 }}>
                                {Object.entries(state.fixResult.fixed_files).map(([fileName, fixedContent], i) => {
                                  const originalContent = state.fixResult?.original_files?.[fileName] || '';
                                  const hasChanges = originalContent !== fixedContent;
                                  
                                  return (
                                    <Box key={i} sx={{ borderTop: i > 0 ? '1px solid #e0e0e0' : 'none' }}>
                                      <Typography variant="body2" sx={{ p: 1.5, bgcolor: '#f5f5f5', fontFamily: 'monospace', fontWeight: 600 }}>
                                        📄 {fileName} {hasChanges ? '(modified)' : '(new file)'}
                                      </Typography>
                                      <Box sx={{ bgcolor: '#1e1e1e', p: 1.5, maxHeight: 400, overflow: 'auto' }}>
                                        {hasChanges && originalContent ? (
                                          // Show unified diff with proper line tracking
                                          <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                            {(() => {
                                              const origLines = originalContent.split('\n');
                                              const fixedLines = (typeof fixedContent === 'string' ? fixedContent : '').split('\n');
                                              
                                              // Simple LCS-based diff algorithm
                                              const computeDiff = (a: string[], b: string[]) => {
                                                const result: Array<{type: 'same' | 'del' | 'add', line: string, oldNum?: number, newNum?: number}> = [];
                                                let ai = 0, bi = 0;
                                                
                                                while (ai < a.length || bi < b.length) {
                                                  if (ai >= a.length) {
                                                    result.push({ type: 'add', line: b[bi], newNum: bi + 1 });
                                                    bi++;
                                                  } else if (bi >= b.length) {
                                                    result.push({ type: 'del', line: a[ai], oldNum: ai + 1 });
                                                    ai++;
                                                  } else if (a[ai] === b[bi]) {
                                                    result.push({ type: 'same', line: a[ai], oldNum: ai + 1, newNum: bi + 1 });
                                                    ai++; bi++;
                                                  } else {
                                                    let foundInB = -1, foundInA = -1;
                                                    for (let look = 1; look < 10; look++) {
                                                      if (foundInB === -1 && bi + look < b.length && a[ai] === b[bi + look]) foundInB = look;
                                                      if (foundInA === -1 && ai + look < a.length && a[ai + look] === b[bi]) foundInA = look;
                                                      if (foundInB !== -1 || foundInA !== -1) break;
                                                    }
                                                    
                                                    if (foundInB !== -1 && (foundInA === -1 || foundInB <= foundInA)) {
                                                      for (let k = 0; k < foundInB; k++) {
                                                        result.push({ type: 'add', line: b[bi + k], newNum: bi + k + 1 });
                                                      }
                                                      bi += foundInB;
                                                    } else if (foundInA !== -1) {
                                                      for (let k = 0; k < foundInA; k++) {
                                                        result.push({ type: 'del', line: a[ai + k], oldNum: ai + k + 1 });
                                                      }
                                                      ai += foundInA;
                                                    } else {
                                                      result.push({ type: 'del', line: a[ai], oldNum: ai + 1 });
                                                      result.push({ type: 'add', line: b[bi], newNum: bi + 1 });
                                                      ai++; bi++;
                                                    }
                                                  }
                                                }
                                                return result;
                                              };
                                              
                                              const diff = computeDiff(origLines, fixedLines);
                                              const CONTEXT = 2;
                                              const changeIndices = new Set<number>();
                                              diff.forEach((d, idx) => {
                                                if (d.type !== 'same') {
                                                  for (let k = Math.max(0, idx - CONTEXT); k <= Math.min(diff.length - 1, idx + CONTEXT); k++) {
                                                    changeIndices.add(k);
                                                  }
                                                }
                                              });
                                              
                                              if (changeIndices.size === 0) {
                                                return <div style={{ color: '#808080' }}>No visible changes</div>;
                                              }
                                              
                                              const sortedIndices = Array.from(changeIndices).sort((a, b) => a - b);
                                              const diffLines: React.ReactNode[] = [];
                                              let lastIdx = -1;
                                              
                                              for (const idx of sortedIndices) {
                                                if (lastIdx !== -1 && idx > lastIdx + 1) {
                                                  diffLines.push(<div key={`sep-${idx}`} style={{ color: '#569cd6', padding: '4px 0' }}>@@ ... @@</div>);
                                                }
                                                lastIdx = idx;
                                                
                                                const d = diff[idx];
                                                const lineNum = d.type === 'del' ? d.oldNum : d.newNum;
                                                
                                                if (d.type === 'del') {
                                                  diffLines.push(<div key={`${idx}-del`} style={{ color: '#f14c4c', backgroundColor: 'rgba(244,76,76,0.15)' }}><span style={{ color: '#666', marginRight: 8, minWidth: 30, display: 'inline-block' }}>{lineNum}</span>- {d.line}</div>);
                                                } else if (d.type === 'add') {
                                                  diffLines.push(<div key={`${idx}-add`} style={{ color: '#4ec9b0', backgroundColor: 'rgba(78,201,176,0.15)' }}><span style={{ color: '#666', marginRight: 8, minWidth: 30, display: 'inline-block' }}>{lineNum}</span>+ {d.line}</div>);
                                                } else {
                                                  diffLines.push(<div key={idx} style={{ color: '#808080' }}><span style={{ color: '#444', marginRight: 8, minWidth: 30, display: 'inline-block' }}>{lineNum}</span>  {d.line}</div>);
                                                }
                                              }
                                              
                                              return diffLines;
                                            })()}
                                          </pre>
                                        ) : (
                                          // Show full content for new files
                                          <pre style={{ margin: 0, fontSize: 11, color: '#4ec9b0', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                            {typeof fixedContent === 'string' ? fixedContent : JSON.stringify(fixedContent, null, 2)}
                                          </pre>
                                        )}
                                      </Box>
                                    </Box>
                                  );
                                })}
                              </AccordionDetails>
                            </Accordion>
                          ) : (
                            <Box sx={{ mb: 2, p: 1.5, bgcolor: '#e8f5e9', borderRadius: 1, border: '1px solid #a5d6a7' }}>
                              <Typography variant="body2" color="success.main">
                                ✅ No file modifications needed - fix was already present or verified
                              </Typography>
                            </Box>
                          )}

                          {/* Next Steps - Only show for individual fixes (Fix This), not for Fix All */}
                          {!fixingAll && !fixAllInProgress && !fixAllChoiceDialog.open && !wasFixAllOperation && (
                            <Box sx={{ mt: 2, p: 2, bgcolor: '#f5f5f5', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                              <Typography variant="subtitle2" fontWeight={600} gutterBottom>🚀 Next Steps</Typography>
                              <Box display="flex" gap={2} flexWrap="wrap">
                                <Button
                                  variant="contained"
                                  color="primary"
                                  startIcon={<Science />}
                                  onClick={() => navigate('/test')}
                                >
                                  🧪 Deploy Draft &amp; Test on AWS
                                </Button>
                              </Box>
                            </Box>
                          )}
                        </Box>
                      )}
                      
                      {status === 'failed' && (
                        <Box>
                          <Typography variant="body2" color="error.main" gutterBottom>
                            The fix could not be applied. You can retry or view details for more information.
                          </Typography>
                          {state?.fixResult?.message && (
                            <Box sx={{ mt: 1, p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #ef9a9a' }}>
                              <Typography variant="caption" color="text.secondary" display="block" gutterBottom>Error Details</Typography>
                              <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                {state.fixResult.message}
                              </Typography>
                            </Box>
                          )}
                          <Box sx={{ mt: 1.5, display: 'flex', gap: 1 }}>
                            <Button 
                              size="small" 
                              variant="outlined" 
                              color="error"
                              startIcon={<Build />}
                              onClick={() => handleFixPattern(cluster)}
                            >
                              🔄 Retry Fix
                            </Button>
                            <Button 
                              size="small" 
                              variant="text"
                              onClick={() => setExpandedPattern(cluster.pattern_id)}
                            >
                              📋 View Error Details
                            </Button>
                          </Box>
                        </Box>
                      )}
                    </Box>
                  )}

                  {/* Expanded Details - Like Streamlit */}
                  <Collapse in={isExpanded}>
                    <Box mt={2} p={2} bgcolor="grey.50" borderRadius={1}>
                      {/* AI Classification Section */}
                      <Typography variant="subtitle2" fontWeight={600} gutterBottom>
                        🤖 AI Classification
                      </Typography>
                      <Box display="grid" gridTemplateColumns="repeat(3, 1fr)" gap={2} mb={3}>
                        <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                          <Typography variant="caption" color="text.secondary">Classification Type</Typography>
                          <Typography variant="body1" fontWeight={600} color="primary.main">
                            {classification?.type?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) || 'Analyzing...'}
                          </Typography>
                        </Box>
                        <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                          <Typography variant="caption" color="text.secondary">Confidence Score</Typography>
                          <Typography variant="h5" fontWeight={600} color="success.main">{confidence}%</Typography>
                        </Box>
                        <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0', gridColumn: 'span 1' }}>
                          <Typography variant="caption" color="text.secondary">Status</Typography>
                          <Typography variant="body1" fontWeight={600}>{statusConfig.icon} {statusConfig.text}</Typography>
                        </Box>
                      </Box>

                      {/* Basic Information Section */}
                      <Typography variant="subtitle2" fontWeight={600} gutterBottom>
                        📋 Error Details
                      </Typography>
                      <Box display="grid" gridTemplateColumns="repeat(2, 1fr)" gap={2} mb={2}>
                        <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                          <Typography variant="caption" color="text.secondary">Error Type</Typography>
                          <Typography variant="body1" fontWeight={600} color="error.main">{cluster.error_type}</Typography>
                        </Box>
                        <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                          <Typography variant="caption" color="text.secondary">Occurrences</Typography>
                          <Typography variant="body1" fontWeight={600}>{cluster.count}</Typography>
                        </Box>
                        <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                          <Typography variant="caption" color="text.secondary">First Seen</Typography>
                          <Typography variant="body2">{cluster.first_seen ? new Date(cluster.first_seen).toLocaleString() : 'N/A'}</Typography>
                        </Box>
                        <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                          <Typography variant="caption" color="text.secondary">Last Seen</Typography>
                          <Typography variant="body2">{cluster.last_seen ? new Date(cluster.last_seen).toLocaleString() : 'N/A'}</Typography>
                        </Box>
                      </Box>
                      
                      {/* Full Error Message */}
                      <Box sx={{ borderTop: '1px solid #ddd', pt: 2, mt: 2 }}>
                        <Typography variant="subtitle2" fontWeight={600} gutterBottom>
                          ❌ Full Error Message
                        </Typography>
                        <pre style={{
                          margin: 0,
                          padding: 10,
                          backgroundColor: '#fff3e0',
                          color: '#e65100',
                          borderRadius: 4,
                          fontSize: 12,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                        }}>
                          {cluster.error_message}
                        </pre>
                      </Box>

                      {/* Stack Trace Section */}
                      {cluster.stack_trace && (
                        <Box sx={{ borderTop: '1px solid #ddd', pt: 2, mt: 2 }}>
                          <Typography variant="subtitle2" fontWeight={600} gutterBottom>
                            📋 Stack Trace
                          </Typography>
                          <pre style={{
                            margin: 0,
                            padding: 10,
                            backgroundColor: '#1e1e1e',
                            color: '#d4d4d4',
                            borderRadius: 4,
                            fontSize: 11,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}>
                            {cluster.stack_trace}
                          </pre>
                        </Box>
                      )}

                      {/* Fix Result Summary */}
                      {state?.fixResult?.code_agent_summary && (
                        <Alert severity="success" sx={{ mt: 2, py: 0.5 }}>
                          <Typography variant="body2"><b>Fix Applied:</b> {state.fixResult.code_agent_summary}</Typography>
                        </Alert>
                      )}
                    </Box>
                  </Collapse>
                </Paper>
              );
            })}
          </Box>
        )}
      </Paper>
      )}

      {/* Global Next Steps - Shows ONLY after Fix All completes (not for individual fixes) */}
      {!fixingAll && !fixAllInProgress && fixedCount > 0 && wasFixAllOperation && (
        <Paper sx={{ p: 3, mt: 3, bgcolor: '#e8f5e9', border: '2px solid #4caf50' }}>
          <Typography variant="h6" fontWeight={600} gutterBottom color="success.main">
            {fixedCount === totalCount ? `🎉 All ${fixedCount} Patterns Fixed!` : `✅ ${fixedCount} of ${totalCount} Patterns Fixed`}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {fixedCount === totalCount 
              ? 'All error patterns have been successfully fixed. Deploy the fix as a draft and test it before promoting:'
              : `${fixedCount} patterns have been fixed. You can deploy and test the changes now, or fix the remaining ${totalCount - fixedCount} patterns.`}
          </Typography>
          <Box display="flex" gap={2} flexWrap="wrap">
            <Button
              variant="contained"
              color="primary"
              size="large"
              startIcon={<Science />}
              onClick={() => navigate('/test')}
            >
              🧪 Deploy Draft &amp; Test on AWS
            </Button>
          </Box>
        </Paper>
      )}

      {/* Choice Dialog - Individual Pattern */}
      <Dialog open={choiceDialog.open} onClose={() => setChoiceDialog({ open: false, patternId: '', cluster: null })} maxWidth="xs" fullWidth>
        <DialogTitle>Choose Fix Approach</DialogTitle>
        <DialogContent>
          <RadioGroup value={selectedChoice} onChange={(e) => setSelectedChoice(e.target.value as UserChoice)}>
            <FormControlLabel value="library" control={<Radio size="small" />} label="📦 Package updates only" />
            <FormControlLabel value="code" control={<Radio size="small" />} label="🔧 Code fix" />
            <FormControlLabel value="both" control={<Radio size="small" />} label="🔀 Both (code + packages)" />
            <FormControlLabel value="skip" control={<Radio size="small" />} label="⏭️ Skip this pattern" />
          </RadioGroup>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setChoiceDialog({ open: false, patternId: '', cluster: null })}>Cancel</Button>
          <Button onClick={handleUserChoice} variant="contained">Apply</Button>
        </DialogActions>
      </Dialog>

      {/* Global Choice Dialog - Fix All */}
      <Dialog 
        open={fixAllChoiceDialog.open} 
        onClose={() => setFixAllChoiceDialog({ open: false, mixedCount: 0, patternsToFix: [] })} 
        maxWidth="sm" 
        fullWidth
      >
        <DialogTitle>🚀 Fix All - {fixAllChoiceDialog.patternsToFix.length} Patterns</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            <Typography variant="body2">
              Ready to fix <strong>{fixAllChoiceDialog.patternsToFix.length}</strong> error patterns.
              {fixAllChoiceDialog.mixedCount > 0 && (
                <> ({fixAllChoiceDialog.mixedCount} have mixed classification)</>
              )}
            </Typography>
          </Alert>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            For patterns that can be fixed with both package updates and code changes, choose your preferred approach:
          </Typography>
          <RadioGroup value={globalMixedChoice} onChange={(e) => setGlobalMixedChoice(e.target.value as UserChoice)}>
            <FormControlLabel value="both" control={<Radio size="small" />} label="🔀 Both - Apply package updates AND code fixes (recommended)" />
            <FormControlLabel value="code" control={<Radio size="small" />} label="🔧 Code only - Only apply code fixes" />
            <FormControlLabel value="library" control={<Radio size="small" />} label="📦 Library only - Only update packages/dependencies" />
            <FormControlLabel value="skip" control={<Radio size="small" />} label="⏭️ Skip mixed - Only fix non-mixed patterns" />
          </RadioGroup>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFixAllChoiceDialog({ open: false, mixedCount: 0, patternsToFix: [] })}>Cancel</Button>
          <Button onClick={handleFixAllWithChoice} variant="contained" color="primary">
            🚀 Start Fix All
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
