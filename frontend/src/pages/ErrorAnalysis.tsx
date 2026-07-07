/**
 * Error Analysis Page
 * Shows error patterns with Fix buttons - consistent with Agent Details page
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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  LinearProgress,
  Collapse,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  RadioGroup,
  FormControlLabel,
  Radio,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Tooltip,
} from '@mui/material';
import { Build, Refresh, Science, RocketLaunch } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useAgents } from '../hooks/useAgents';
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

const classificationStyles: Record<string, { bg: string; label: string; icon: string }> = {
  code_fix_required: { bg: '#1f77b4', label: 'Code', icon: '🔧' },
  package_only: { bg: '#ff7f0e', label: 'Library', icon: '📦' },
  mixed: { bg: '#9467bd', label: 'Mixed', icon: '🔀' },
};

export const ErrorAnalysis: React.FC = () => {
  const navigate = useNavigate();
  const [timeRange, setTimeRange] = useState<TimeRange>(() => {
    const { startTime, endTime } = getTimeRangeFromPreset('24h');
    return { preset: '24h', startTime, endTime };
  });
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
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

  const { 
    setSelectedAgent, 
    setWorkingDirectory,
    setFixAllWorkingDirectory,
    workingDirectory,
    fixAllWorkingDirectory,
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
  const canFix = hasRole('operator');  const { data: agentsData } = useAgents({ limit: 100 });

  // Use the same error clusters API as Agent Details
  const { 
    data: clustersResponse, 
    isLoading: clustersLoading, 
    refetch: refetchClusters 
  } = useErrorClusters(
    selectedAgentId || '',
    { 
      limit: 20,
      start_time: timeRange.startTime,
      end_time: timeRange.endTime,
    },
    { enabled: !!selectedAgentId }
  );
  
  // Extract clusters and suppression summary from response
  const errorClusters = clustersResponse?.clusters || [];
  const suppressionSummary: SuppressionSummary | undefined = clustersResponse?.suppression_summary;

  const analyzeErrorMutation = useAnalyzeError();
  const startFixMutation = useStartFixWorkflow();

  // NOTE: We intentionally do NOT auto-restore the agent from workflow store
  // User must explicitly select an agent to see errors
  // This prevents confusion when navigating to the page

  // Clear local state when agent changes to prevent stale data
  const [previousAgentId, setPreviousAgentId] = useState<string>('');
  useEffect(() => {
    if (selectedAgentId && selectedAgentId !== previousAgentId) {
      // Agent changed - clear all local state
      setPatternStates(new Map());
      setHasRestoredFixedPatterns(false);
      setHasRestoredInProgress(false);
      setCurrentFixingPattern(null);
      setExpandedPattern(null);
      setFixingAll(false);
      setFixAllInProgress(false);
      setFixAllQueue([]);
      setPreviousAgentId(selectedAgentId);
    }
  }, [selectedAgentId, previousAgentId]);

  // Set selected agent in workflow store
  useEffect(() => {
    if (selectedAgentId) {
      const agent = agentsData?.agents.find(a => a.agent_id === selectedAgentId);
      if (agent) setSelectedAgent(selectedAgentId, agent.name);
    }
  }, [selectedAgentId, agentsData, setSelectedAgent]);

  // Track if we've restored fixed patterns (to prevent auto-classify from overwriting)
  const [hasRestoredFixedPatterns, setHasRestoredFixedPatterns] = useState(false);

  // Restore pattern states from fixedPatterns FIRST - before auto-classify runs
  // This runs whenever fixedPatterns changes or component mounts
  useEffect(() => {
    if (selectedAgentId && fixedPatterns.length > 0) {
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
      setHasRestoredFixedPatterns(true);
    } else if (selectedAgentId) {
      // No fixed patterns to restore, allow auto-classify
      setHasRestoredFixedPatterns(true);
    }
  }, [selectedAgentId, fixedPatterns]);

  // Track which patterns have been queued for analysis (prevents duplicate calls)
  const analyzedPatternsRef = React.useRef<Set<string>>(new Set());
  
  // Reset the ref when agent changes
  useEffect(() => {
    if (selectedAgentId) {
      analyzedPatternsRef.current = new Set();
    }
  }, [selectedAgentId]);

  // Auto-classify patterns when loaded - run SEQUENTIALLY to avoid race conditions
  // Only runs AFTER fixed patterns have been restored
  useEffect(() => {
    if (!hasRestoredFixedPatterns) return; // Wait for restore to complete
    
    const classifyPatternsSequentially = async () => {
      if (!errorClusters || errorClusters.length === 0 || !selectedAgentId) return;
      
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
  }, [errorClusters, selectedAgentId, hasRestoredFixedPatterns]);

  const updatePatternState = useCallback((patternId: string, updates: Partial<PatternState>) => {
    setPatternStates(prev => {
      const newMap = new Map(prev);
      newMap.set(patternId, { ...(newMap.get(patternId) || { status: 'pending' as PatternStatus }), ...updates });
      return newMap;
    });
  }, []);

  // Track if we've already handled the initial in-progress fix restoration
  const [hasRestoredInProgress, setHasRestoredInProgress] = useState(false);
  
  // Restore in-progress fix state ONLY on initial page load (survives refresh)
  // This should NOT run when we set inProgressFix during normal fix operations
  useEffect(() => {
    // Only restore once on initial load, not on every inProgressFix change
    if (!hasRestoredInProgress && inProgressFix && inProgressFix.agentId === selectedAgentId && selectedAgentId) {
      // Check if this is a stale in-progress fix (older than 10 minutes)
      const startedAt = new Date(inProgressFix.startedAt).getTime();
      const now = Date.now();
      const tenMinutes = 10 * 60 * 1000;
      
      if (now - startedAt > tenMinutes) {
        // Stale fix - just clear it
        clearInProgressFix();
      }
      // Don't set currentFixingPattern or processing state
      // The warning will show and user can dismiss it
      setHasRestoredInProgress(true);
    }
  }, [inProgressFix, selectedAgentId, hasRestoredInProgress, clearInProgressFix]);

  const analyzePattern = useCallback(async (cluster: ErrorCluster) => {
    if (!selectedAgentId) return null;
    const currentState = patternStates.get(cluster.pattern_id);
    if (currentState?.classification) return currentState.classification;
    
    // Debug: Log what we're sending
    console.log(`[CLASSIFY] Sending: pattern_id=${cluster.pattern_id}, error="${cluster.error_message.slice(0, 50)}..."`);
    
    updatePatternState(cluster.pattern_id, { status: 'analyzing' });
    try {
      const result = await analyzeErrorMutation.mutateAsync({ agentId: selectedAgentId, errorCluster: cluster });
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
  }, [selectedAgentId, analyzeErrorMutation, updatePatternState, patternStates]);

  const handleFixPattern = useCallback(async (cluster: ErrorCluster, userChoice?: UserChoice, isPartOfFixAll?: boolean, fixAllSessionId?: string) => {
    if (!selectedAgentId) return;
    
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
    
    // Note: We no longer set inProgressFix during normal operations
    // It was causing the warning to appear during active fixes
    // The progress bar is shown based on currentFixingPattern and status instead
    const isInFixAll = isPartOfFixAll || inProgressFix?.isFixAll;
    
    // Get session ID from parameter or from inProgressFix
    const sessionId = fixAllSessionId || inProgressFix?.fixAllSessionId;
    
    // If this is an individual fix (not part of Fix All), reset the flag
    if (!isInFixAll) {
      setWasFixAllOperation(false);
    }
    
    try {
      // Get pre-computed analysis to avoid redundant classification (saves ~10s)
      const preAnalysis = patternState?.analysisResult;
      
      const result = await startFixMutation.mutateAsync({
        agentId: selectedAgentId, 
        patternId: cluster.pattern_id, 
        errorCluster: cluster, 
        userChoice,
        isFixAll: isInFixAll,  // Pass to backend for shared/separate workspace decision
        fixAllSessionId: sessionId,  // Pass session ID for workspace isolation
        preAnalysis,  // Pass pre-computed analysis to skip redundant classification
      });

      // Debug logging
      console.log('=== FIX RESULT RECEIVED ===');
      console.log('result.status:', result.status);
      console.log('result.workflow_type:', result.workflow_type);
      console.log('result.fixed_files:', Object.keys(result.fixed_files || {}));
      console.log('result.message:', result.message);
      console.log('Full result:', result);
      console.log('===========================');

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
          // This ensures Test on AWS uses the correct shared workspace
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
    }
  }, [selectedAgentId, startFixMutation, updatePatternState, setWorkingDirectory, setFixAllWorkingDirectory, addFixedPattern, inProgressFix]);
  // Note: patternStates removed from deps - we access it via closure but don't need to recreate callback when it changes

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
      // Remove the current pattern from queue and continue
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

  // Queue for Fix All - stores patterns waiting to be processed after user makes choices
  const [fixAllQueue, setFixAllQueue] = useState<ErrorCluster[]>([]);
  const [fixAllInProgress, setFixAllInProgress] = useState(false);

  const handleFixAllPatterns = async () => {
    console.log('[Fix All] handleFixAllPatterns called');
    console.log('[Fix All] errorClusters:', errorClusters?.length);
    console.log('[Fix All] selectedAgentId:', selectedAgentId);
    
    if (!errorClusters || !selectedAgentId) {
      console.log('[Fix All] Early return - no clusters or agent');
      return;
    }
    
    // Build queue of patterns that need fixing
    // Include: pending, failed, analyzing (not yet classified), or no state
    // Exclude: fixed, processing, awaiting_choice
    const patternsToFix: ErrorCluster[] = [];
    for (const cluster of errorClusters) {
      const state = patternStates.get(cluster.pattern_id);
      console.log(`[Fix All] Pattern ${cluster.pattern_id.slice(0, 20)}: status=${state?.status}, classification=${state?.classification?.type}`);
      const status = state?.status;
      // Include patterns that are not yet fixed or being processed
      if (!state || status === 'pending' || status === 'failed' || status === 'analyzing') {
        patternsToFix.push(cluster);
      }
    }
    
    console.log('[Fix All] patternsToFix:', patternsToFix.length);
    
    if (patternsToFix.length === 0) {
      console.log('[Fix All] No patterns to fix');
      return;
    }
    
    // Count mixed patterns - log each pattern's classification for debugging
    const mixedPatterns = patternsToFix.filter(cluster => {
      const state = patternStates.get(cluster.pattern_id);
      const classType = state?.classification?.type;
      console.log(`[Fix All] Checking pattern ${cluster.pattern_id.slice(0, 20)}: classification.type="${classType}"`);
      return classType === 'mixed';
    });
    
    console.log('[Fix All] mixedPatterns count:', mixedPatterns.length);
    console.log('[Fix All] Total patternsToFix:', patternsToFix.length);
    
    // Only show choice dialog if there are MIXED patterns
    // If all patterns are code-only or library-only, proceed directly WITHOUT dialog
    if (mixedPatterns.length > 0) {
      console.log('[Fix All] HAS MIXED PATTERNS - showing choice dialog');
      setFixAllChoiceDialog({
        open: true,
        mixedCount: mixedPatterns.length,
        patternsToFix,
      });
    } else {
      console.log('[Fix All] NO MIXED PATTERNS - skipping dialog, starting fix immediately');
      // No mixed patterns - start fixing immediately without asking user
      await startFixAllExecution(patternsToFix);
    }
  };
  
  // Start Fix All execution after choice is made (or if no mixed patterns)
  const startFixAllExecution = async (patternsToFix: ErrorCluster[]) => {
    if (!selectedAgentId) return;
    
    // Generate unique session ID for this Fix All operation
    // This ensures each user/session gets their own workspace
    const sessionId = `fixall_${Date.now().toString(36)}_${crypto.randomUUID().slice(0, 8)}`;
    
    setWasFixAllOperation(true); // Mark that this is a Fix All operation
    setFixingAll(true);
    setFixAllInProgress(true);
    
    // Track Fix All in persisted store (including session ID)
    setInProgressFix({
      patternId: patternsToFix[0].pattern_id,
      agentId: selectedAgentId,
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
  
  // Handle global choice for Fix All mixed patterns
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
      // Proceed with all patterns using the global choice for mixed ones
      await startFixAllExecution(patternsToFix);
    }
  };

  const processFixAllQueue = async (queue: ErrorCluster[], sessionId?: string) => {
    const totalInQueue = queue.length;
    for (let i = 0; i < queue.length; i++) {
      const cluster = queue[i];
      const state = patternStates.get(cluster.pattern_id);
      
      // Skip if already fixed
      if (state?.status === 'fixed') {
        // Update progress for skipped items
        if (inProgressFix?.isFixAll) {
          setInProgressFix({
            ...inProgressFix,
            fixAllCompleted: (inProgressFix.fixAllCompleted || 0) + 1,
          });
        }
        continue;
      }
      
      // Update current pattern in progress tracking
      if (inProgressFix?.isFixAll && selectedAgentId) {
        setInProgressFix({
          ...inProgressFix,
          patternId: cluster.pattern_id,
          fixAllCompleted: i,
        });
      }
      
      // Get or compute classification
      const classification = state?.classification || await analyzePattern(cluster);
      
      // Debug: log classification for Fix All
      console.log(`[Fix All] Pattern ${i + 1}/${queue.length}: ${cluster.pattern_id.slice(0, 20)}...`);
      console.log(`[Fix All] Classification type: "${classification?.type}", confidence: ${classification?.confidence}`);
      console.log(`[Fix All] Session ID: ${sessionId}`);
      
      // If mixed, use the global choice that was selected upfront
      if (classification?.type === 'mixed') {
        console.log(`[Fix All] Mixed classification - using global choice: ${globalMixedChoice}`);
        await handleFixPattern(cluster, globalMixedChoice, true, sessionId); // true = part of Fix All
      } else {
        // For non-mixed, proceed directly
        console.log(`[Fix All] Non-mixed (${classification?.type}) - proceeding with fix`);
        await handleFixPattern(cluster, undefined, true, sessionId); // true = part of Fix All
      }
    }
    
    // All done - wasFixAllOperation stays true so Next Steps don't show on individual cards
    setFixingAll(false);
    setFixAllInProgress(false);
    setFixAllQueue([]);
    clearInProgressFix();
  };

  const fixedCount = errorClusters?.filter(c => patternStates.get(c.pattern_id)?.status === 'fixed').length || 0;
  const totalCount = errorClusters?.length || 0;

  return (
    <Box sx={{ p: 2, maxWidth: 1200 }}>
      <Typography variant="h5" fontWeight={600} gutterBottom>
        Error Analysis
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Analyze and fix errors across your agents
      </Typography>

      {/* Global In-Progress Fix Warning (shows even before agent selection) */}
      {inProgressFix && !selectedAgentId && (
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
              }}
            >
              Dismiss
            </Button>
          }
        >
          <Typography variant="body2">
            <strong>Fix in progress:</strong> A fix operation for agent "{inProgressFix.agentId}" was started at {new Date(inProgressFix.startedAt).toLocaleTimeString()}.
            Select the agent to see status, or dismiss this warning.
          </Typography>
        </Alert>
      )}

      {/* Filters */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box display="flex" gap={2} flexWrap="wrap" alignItems="flex-start">
          <TimeRangeSelector value={timeRange} onChange={setTimeRange} showCustom={true} />
          <FormControl size="small" sx={{ minWidth: 250 }}>
            <InputLabel>Select Agent *</InputLabel>
            <Select
              value={selectedAgentId}
              label="Select Agent *"
              onChange={(e) => setSelectedAgentId(e.target.value)}
            >
              <MenuItem value="" disabled>-- Select an agent --</MenuItem>
              {/* Sort agents to show test_customer_agent first */}
              {agentsData?.agents && [...agentsData.agents].sort((a, b) => {
                const priorityAgent = 'test_customer_agent';
                const aIsPriority = a.name?.includes(priorityAgent) || a.agent_id?.includes(priorityAgent);
                const bIsPriority = b.name?.includes(priorityAgent) || b.agent_id?.includes(priorityAgent);
                if (aIsPriority && !bIsPriority) return -1;
                if (!aIsPriority && bIsPriority) return 1;
                return 0;
              }).map((agent) => (
                <MenuItem key={agent.agent_id} value={agent.agent_id}>
                  {agent.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button 
            variant="outlined" 
            startIcon={<Refresh />} 
            onClick={async () => {
              // Force refresh from backend (bypass cache)
              await fixApi.getErrorClusters(selectedAgentId, {
                start_time: timeRange.startTime,
                end_time: timeRange.endTime,
                limit: 20,
                refresh: true,
              });
              refetchClusters();
              // Also restore fixed patterns from store (including classification)
              if (fixedPatterns.length > 0) {
                setPatternStates(prev => {
                  const newMap = new Map(prev);
                  fixedPatterns.forEach(fp => {
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
              }
            }}
            disabled={!selectedAgentId}
          >
            Refresh
          </Button>
        </Box>
      </Paper>

      {/* No agent selected */}
      {!selectedAgentId && (
        <Alert severity="info">
          Please select an agent to view and fix error patterns.
        </Alert>
      )}

      {/* Error Patterns - Same layout as Agent Details */}
      {selectedAgentId && (
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
            <Box display="flex" justifyContent="center" p={4}><CircularProgress /></Box>
          ) : !errorClusters?.length ? (
            <Alert severity="success">No errors found for this agent in the selected time range ({timeRange.preset === 'custom' ? 'custom range' : timeRange.preset}) 🎉</Alert>
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
                    }}
                  >
                    {/* Error Header */}
                    <Box sx={{ p: 1.5, mb: 2, borderRadius: 1, bgcolor: cluster.error_type.includes('Error') ? '#ffebee' : '#fff3e0' }}>
                      <Typography variant="subtitle1" fontWeight={600} color={cluster.error_type.includes('Error') ? 'error.main' : 'warning.main'}>
                        🔴 #{idx + 1} {cluster.error_type}: {cluster.error_message.slice(0, 80)}{cluster.error_message.length > 80 ? '...' : ''}
                      </Typography>
                    </Box>

                    {/* Badges Row */}
                    <Box display="flex" alignItems="center" gap={2} flexWrap="wrap" mb={1}>
                      {classification ? (
                        <Box sx={{ px: 1.5, py: 0.75, borderRadius: 1, bgcolor: classStyle?.bg || '#666', color: 'white', fontSize: 12 }}>
                          {classStyle?.icon} {classStyle?.label} ({confidence}%)
                        </Box>
                      ) : status === 'analyzing' ? (
                        <Box display="flex" alignItems="center" gap={1}><CircularProgress size={16} /><Typography variant="caption">Classifying...</Typography></Box>
                      ) : null}
                      <Box sx={{ px: 1.5, py: 0.75, borderRadius: 1, bgcolor: statusConfig.bg, color: 'white', fontSize: 12 }}>
                        {statusConfig.icon} {statusConfig.text}
                      </Box>
                      <Box sx={{ px: 1.5, py: 0.5, bgcolor: 'grey.100', borderRadius: 1 }}>
                        <Typography variant="body2"><b>{cluster.count}</b> occurrences</Typography>
                      </Box>
                      <Box flex={1} />
                      <Button variant="outlined" size="small" onClick={() => setExpandedPattern(isExpanded ? null : cluster.pattern_id)}>
                        {isExpanded ? '▲ Hide' : '▼ Details'}
                      </Button>
                      <Button
                        variant={status === 'fixed' ? 'outlined' : 'contained'}
                        color={status === 'fixed' ? 'success' : status === 'failed' ? 'error' : 'primary'}
                        size="small"
                        startIcon={isFixing ? <CircularProgress size={14} color="inherit" /> : <Build />}
                        onClick={() => handleFixPattern(cluster)}
                        disabled={!!currentFixingPattern || status === 'analyzing' || status === 'processing' || status === 'fixed' || !canFix}
                      >
                        {status === 'fixed' ? 'Fixed ✓' : status === 'failed' ? 'Retry' : 'Fix This'}
                      </Button>
                    </Box>

                    {/* AI Reasoning */}
                    {classification?.reasoning && (
                      <Box sx={{ mt: 1.5, p: 1.5, bgcolor: '#e3f2fd', borderRadius: 1, border: '1px solid #90caf9' }}>
                        <Typography variant="body2">💭 <b>AI Analysis:</b> {classification.reasoning}</Typography>
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
                                                      // Rest of b are additions
                                                      result.push({ type: 'add', line: b[bi], newNum: bi + 1 });
                                                      bi++;
                                                    } else if (bi >= b.length) {
                                                      // Rest of a are deletions
                                                      result.push({ type: 'del', line: a[ai], oldNum: ai + 1 });
                                                      ai++;
                                                    } else if (a[ai] === b[bi]) {
                                                      // Same line
                                                      result.push({ type: 'same', line: a[ai], oldNum: ai + 1, newNum: bi + 1 });
                                                      ai++; bi++;
                                                    } else {
                                                      // Look ahead to find best match
                                                      let foundInB = -1, foundInA = -1;
                                                      for (let look = 1; look < 10; look++) {
                                                        if (foundInB === -1 && bi + look < b.length && a[ai] === b[bi + look]) foundInB = look;
                                                        if (foundInA === -1 && ai + look < a.length && a[ai + look] === b[bi]) foundInA = look;
                                                        if (foundInB !== -1 || foundInA !== -1) break;
                                                      }
                                                      
                                                      if (foundInB !== -1 && (foundInA === -1 || foundInB <= foundInA)) {
                                                        // Lines were added in b
                                                        for (let k = 0; k < foundInB; k++) {
                                                          result.push({ type: 'add', line: b[bi + k], newNum: bi + k + 1 });
                                                        }
                                                        bi += foundInB;
                                                      } else if (foundInA !== -1) {
                                                        // Lines were deleted from a
                                                        for (let k = 0; k < foundInA; k++) {
                                                          result.push({ type: 'del', line: a[ai + k], oldNum: ai + k + 1 });
                                                        }
                                                        ai += foundInA;
                                                      } else {
                                                        // Line changed
                                                        result.push({ type: 'del', line: a[ai], oldNum: ai + 1 });
                                                        result.push({ type: 'add', line: b[bi], newNum: bi + 1 });
                                                        ai++; bi++;
                                                      }
                                                    }
                                                  }
                                                  return result;
                                                };
                                                
                                                const diff = computeDiff(origLines, fixedLines);
                                                
                                                // Filter to show only changes with context
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
                                <Box display="flex" gap={2} flexWrap="wrap" mb={2}>
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

                    {/* Expanded Details */}
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
                              {classification?.type?.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase()) || 'Analyzing...'}
                            </Typography>
                          </Box>
                          <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                            <Typography variant="caption" color="text.secondary">Confidence Score</Typography>
                            <Typography variant="h5" fontWeight={600} color="success.main">{confidence}%</Typography>
                          </Box>
                          <Box sx={{ p: 1.5, bgcolor: 'white', borderRadius: 1, border: '1px solid #e0e0e0' }}>
                            <Typography variant="caption" color="text.secondary">Status</Typography>
                            <Typography variant="body1" fontWeight={600}>{statusConfig.icon} {statusConfig.text}</Typography>
                          </Box>
                        </Box>

                        {/* Error Details Section */}
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
                          <Typography variant="subtitle2" fontWeight={600} gutterBottom>❌ Full Error Message</Typography>
                          <pre style={{ margin: 0, padding: 10, backgroundColor: '#fff3e0', color: '#e65100', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            {cluster.error_message}
                          </pre>
                        </Box>
                        {cluster.stack_trace && (
                          <Box sx={{ borderTop: '1px solid #ddd', pt: 2, mt: 2 }}>
                            <Typography variant="subtitle2" fontWeight={600} gutterBottom>📋 Stack Trace</Typography>
                            <pre style={{ margin: 0, padding: 10, backgroundColor: '#1e1e1e', color: '#d4d4d4', borderRadius: 4, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                              {cluster.stack_trace}
                            </pre>
                          </Box>
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
      {selectedAgentId && !fixingAll && !fixAllInProgress && fixedCount > 0 && wasFixAllOperation && (
        <Paper sx={{ p: 3, mt: 3, bgcolor: '#e8f5e9', border: '2px solid #4caf50' }}>
          <Typography variant="h6" fontWeight={600} gutterBottom color="success.main">
            {fixedCount === totalCount ? `🎉 All ${fixedCount} Patterns Fixed!` : `✅ ${fixedCount} of ${totalCount} Patterns Fixed`}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {fixedCount === totalCount 
              ? 'All error patterns have been successfully fixed. Deploy the fix as a draft and test it before promoting:'
              : `${fixedCount} patterns have been fixed. You can deploy and test the changes now, or fix the remaining ${totalCount - fixedCount} patterns.`}
          </Typography>
          <Box display="flex" gap={2} flexWrap="wrap" mb={2}>
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
            <FormControlLabel value="both" control={<Radio size="small" />} label="🔀 Both" />
            <FormControlLabel value="skip" control={<Radio size="small" />} label="⏭️ Skip" />
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
        maxWidth="xs" 
        fullWidth
      >
        <DialogTitle>Fix All — {fixAllChoiceDialog.patternsToFix.length} Patterns</DialogTitle>
        <DialogContent>
          {fixAllChoiceDialog.mixedCount > 0 && (
            <Alert severity="info" sx={{ mb: 2, py: 0.5 }}>
              {fixAllChoiceDialog.mixedCount} pattern(s) have mixed classification
            </Alert>
          )}
          <RadioGroup value={globalMixedChoice} onChange={(e) => setGlobalMixedChoice(e.target.value as UserChoice)}>
            <FormControlLabel value="both" control={<Radio size="small" />} label="🔀 Both" />
            <FormControlLabel value="code" control={<Radio size="small" />} label="🔧 Code fix" />
            <FormControlLabel value="library" control={<Radio size="small" />} label="📦 Package updates only" />
            <FormControlLabel value="skip" control={<Radio size="small" />} label="⏭️ Skip mixed" />
          </RadioGroup>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFixAllChoiceDialog({ open: false, mixedCount: 0, patternsToFix: [] })}>Cancel</Button>
          <Button onClick={handleFixAllWithChoice} variant="contained">Start Fix All</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};
