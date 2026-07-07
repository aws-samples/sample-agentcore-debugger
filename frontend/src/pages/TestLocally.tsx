/**
 * Test Agent Page — deploy the fix as a draft, test it, then promote.
 *
 * The fixed code is packaged and deployed as a new draft version on AgentCore
 * (a container image is rebuilt for container agents; code agents deploy directly
 * from S3). Production stays on its current version until the draft is promoted.
 */
import React, { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Button,
  TextField,
  Alert,
  CircularProgress,
  Stepper,
  Step,
  StepLabel,
  StepContent,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Divider,
  LinearProgress,
} from '@mui/material';
import {
  ExpandMore as ExpandMoreIcon,
  CheckCircle,
  Error as ErrorIcon,
  RocketLaunch,
  Send,
  ArrowUpward,
  Delete,
  ArrowBack,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import {
  useBuildAndTest,
  useBuildStatus,
  useInvokeTest,
  usePromoteDraft,
  useDiscardDraft,
} from '../hooks/useTestAgent';
import { useWorkflowStore } from '../stores/workflowStore';
import { useAuthStore } from '../stores/authStore';

interface TestHistoryItem {
  prompt: string;
  success: boolean;
  response?: string;
  error?: string;
  timestamp: string;
}

const PHASE_LABELS: Record<string, { label: string; progress: number }> = {
  preparing: { label: 'Preparing...', progress: 10 },
  packaging: { label: 'Packaging fixed code...', progress: 20 },
  uploading: { label: 'Uploading to S3...', progress: 30 },
  building: { label: 'Building image (2-5 min)...', progress: 50 },
  deploying: { label: 'Deploying draft to AgentCore...', progress: 80 },
  ready: { label: 'Ready to test!', progress: 100 },
  failed: { label: 'Build failed', progress: 0 },
};

export const TestLocally: React.FC = () => {
  const navigate = useNavigate();
  const { hasRole } = useAuthStore();

  const {
    selectedAgentId,
    selectedAgentName,
    getTestWorkingDirectory,
  } = useWorkflowStore();

  const workingDir = getTestWorkingDirectory() || '';

  // State
  const [activeStep, setActiveStep] = useState(0);
  const [buildId, setBuildId] = useState<string | null>(null);
  const [draftVersion, setDraftVersion] = useState('');
  const [productionVersion, setProductionVersion] = useState('');
  const [agentArn, setAgentArn] = useState('');
  const [testPrompt, setTestPrompt] = useState('');
  const [testHistory, setTestHistory] = useState<TestHistoryItem[]>([]);
  const [promoteMessage, setPromoteMessage] = useState('');

  const [buildError, setBuildError] = useState<string | null>(null);

  // Mutations
  const buildAndTest = useBuildAndTest();
  const invokeTest = useInvokeTest();
  const promoteDraft = usePromoteDraft();
  const discardDraft = useDiscardDraft();

  // Poll build progress
  const { data: buildStatus } = useBuildStatus(buildId, {
    enabled: !!buildId,
  });

  // React to build status changes
  useEffect(() => {
    if (!buildStatus) return;
    if (buildStatus.status === 'ready') {
      setDraftVersion(buildStatus.version);
      setProductionVersion(buildStatus.production_version || '');
      // invoke_test needs the runtime ARN (with qualifier='test'), not the runtime id
      setAgentArn(buildStatus.agent_arn || '');
      setBuildId(null); // Stop polling
      setActiveStep(1);
    } else if (buildStatus.status === 'failed') {
      setBuildId(null);
    }
  }, [buildStatus]);

  // ── Handlers ──────────────────────────────────────────────────────────

  const handleBuildAndTest = async () => {
    if (!selectedAgentId || !selectedAgentName || !workingDir) return;
    setBuildError(null);
    try {
      const result = await buildAndTest.mutateAsync({
        agentRuntimeId: selectedAgentId,
        agentName: selectedAgentName,
        workingDirectory: workingDir,
      });
      if (result.status === 'started') {
        setBuildId(result.build_id);
      } else if (result.status === 'failed') {
        setBuildError(result.error || result.message || 'Build failed');
      }
    } catch (e: any) {
      setBuildError(e?.message || 'Build request failed');
    }
  };

  const handleTestPrompt = async () => {
    if (!agentArn || !testPrompt.trim()) return;
    try {
      const result = await invokeTest.mutateAsync({
        agentRuntimeArn: agentArn,
        prompt: testPrompt,
      });
      setTestHistory((prev) => [
        {
          prompt: testPrompt,
          success: result.status === 'success',
          response: result.response,
          error: result.error,
          timestamp: new Date().toISOString(),
        },
        ...prev,
      ]);
      setTestPrompt('');
    } catch (e) {
      console.error('Test failed:', e);
    }
  };

  const handlePromote = async () => {
    if (!selectedAgentId) return;
    const result = await promoteDraft.mutateAsync(selectedAgentId);
    setPromoteMessage(result?.message || '');
    setActiveStep(2);
  };

  const handleDiscard = async () => {
    if (!selectedAgentId) return;
    await discardDraft.mutateAsync(selectedAgentId);
    setActiveStep(0);
    setDraftVersion('');
    setProductionVersion('');
    setTestHistory([]);
  };

  // ── No agent ──────────────────────────────────────────────────────────

  if (!selectedAgentId) {
    return (
      <Container maxWidth="md">
        <Box py={3}>
          <Typography variant="h4" gutterBottom>🧪 Test Agent</Typography>
          <Alert severity="info" sx={{ mt: 3 }}>No active fix session. Fix an agent first.</Alert>
          <Button variant="contained" sx={{ mt: 2 }} onClick={() => navigate('/errors')}>
            Go to Error Analysis
          </Button>
        </Box>
      </Container>
    );
  }

  const currentPhase = buildStatus?.status || '';
  const phaseInfo = PHASE_LABELS[currentPhase] || { label: '', progress: 0 };

  return (
    <Container maxWidth="lg">
      <Box py={3}>
        <Typography variant="h4" gutterBottom>🧪 Test Agent</Typography>
        <Typography variant="subtitle1" color="text.secondary" gutterBottom>
          Build, deploy as draft, and test — production stays untouched
        </Typography>

        <Box display="flex" gap={2} mb={2}>
          <Chip label={`Agent: ${selectedAgentName}`} color="primary" />
          <Button variant="outlined" size="small" startIcon={<ArrowBack />} onClick={() => navigate(-1)}>
            Back
          </Button>
        </Box>

        <Paper sx={{ p: 3 }}>
          <Stepper activeStep={activeStep} orientation="vertical">

            {/* Step 1: Build & Deploy Draft */}
            <Step>
              <StepLabel>
                <Typography variant="subtitle1" fontWeight={600}>🚀 Build & Deploy Draft</Typography>
              </StepLabel>
              <StepContent>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  We'll package your fixed code and deploy it as a new draft version on AgentCore
                  (rebuilding the container image for container agents). Production is not affected
                  until you promote.
                </Typography>

                {/* Build progress */}
                {buildId && buildStatus && (
                  <Box sx={{ mb: 2 }}>
                    <Box display="flex" alignItems="center" gap={1} mb={1}>
                      {buildStatus.status === 'failed' ? (
                        <ErrorIcon color="error" fontSize="small" />
                      ) : (
                        <CircularProgress size={16} />
                      )}
                      <Typography variant="body2">{buildStatus.message || phaseInfo.label}</Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={phaseInfo.progress}
                      color={buildStatus.status === 'failed' ? 'error' : 'primary'}
                    />
                    <Box display="flex" justifyContent="space-between" mt={0.5}>
                      {Object.entries(PHASE_LABELS).filter(([k]) => k !== 'failed').map(([key, val]) => (
                        <Typography
                          key={key}
                          variant="caption"
                          color={currentPhase === key ? 'primary' : 'text.disabled'}
                          fontWeight={currentPhase === key ? 600 : 400}
                        >
                          {val.label.replace('...', '')}
                        </Typography>
                      ))}
                    </Box>
                  </Box>
                )}

                {buildStatus?.status === 'failed' && (
                  <Alert severity="error" sx={{ mb: 2 }}>{buildStatus.message}</Alert>
                )}

                {buildAndTest.isError && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    {(buildAndTest.error as Error)?.message}
                  </Alert>
                )}

                {buildError && (
                  <Alert severity="error" sx={{ mb: 2 }} onClose={() => setBuildError(null)}>
                    {buildError}
                  </Alert>
                )}

                <Button
                  variant="contained"
                  size="large"
                  startIcon={buildId ? <CircularProgress size={20} /> : <RocketLaunch />}
                  onClick={handleBuildAndTest}
                  disabled={!!buildId || buildAndTest.isPending || !workingDir}
                >
                  {buildId ? 'Deploying...' : 'Deploy Draft'}
                </Button>

                {!workingDir && (
                  <Alert severity="warning" sx={{ mt: 2 }}>
                    No working directory found. Go back and fix an error first.
                  </Alert>
                )}
              </StepContent>
            </Step>

            {/* Step 2: Test Prompts */}
            <Step>
              <StepLabel>
                <Typography variant="subtitle1" fontWeight={600}>🧪 Test Prompts</Typography>
              </StepLabel>
              <StepContent>
                {draftVersion && (
                  <Alert severity="success" sx={{ mb: 2 }} icon={<CheckCircle />}>
                    Draft version <strong>{draftVersion}</strong> deployed.
                    {productionVersion && (
                      <> Production still serves <strong>v{productionVersion}</strong> (untouched).</>
                    )}
                    {' '}Send prompts below to verify the fix, then promote.
                  </Alert>
                )}

                <Box display="flex" gap={2} alignItems="flex-start" mb={2}>
                  <TextField
                    fullWidth
                    label="Test prompt"
                    placeholder="Enter a prompt to test the fixed agent..."
                    value={testPrompt}
                    onChange={(e) => setTestPrompt(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleTestPrompt()}
                  />
                  <Button
                    variant="contained"
                    startIcon={invokeTest.isPending ? <CircularProgress size={20} /> : <Send />}
                    onClick={handleTestPrompt}
                    disabled={!testPrompt.trim() || invokeTest.isPending}
                    sx={{ minWidth: 130, height: 56 }}
                  >
                    {invokeTest.isPending ? 'Sending...' : 'Send'}
                  </Button>
                </Box>

                {testHistory.length > 0 && (
                  <Box mb={2}>
                    <Typography variant="subtitle2" gutterBottom>Test Results</Typography>
                    {testHistory.map((item, i) => (
                      <Accordion key={i} defaultExpanded={i === 0}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Box display="flex" alignItems="center" gap={1}>
                            {item.success ? <CheckCircle color="success" fontSize="small" /> : <ErrorIcon color="error" fontSize="small" />}
                            <Typography variant="body2" fontFamily="monospace">{item.prompt}</Typography>
                          </Box>
                        </AccordionSummary>
                        <AccordionDetails>
                          {item.response && (
                            <Box sx={{ p: 1.5, bgcolor: 'grey.50', borderRadius: 1, fontFamily: 'monospace', fontSize: 13, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                              {item.response}
                            </Box>
                          )}
                          {item.error && <Alert severity="error" sx={{ mt: 1 }}>{item.error}</Alert>}
                        </AccordionDetails>
                      </Accordion>
                    ))}
                  </Box>
                )}

                <Divider sx={{ my: 2 }} />

                <Box display="flex" gap={2}>
                  <Button variant="contained" color="success" startIcon={<ArrowUpward />} onClick={handlePromote} disabled={promoteDraft.isPending || !hasRole('admin')}>
                    {promoteDraft.isPending ? 'Promoting...' : 'Promote to Production'}
                  </Button>
                  <Button variant="outlined" color="error" startIcon={<Delete />} onClick={handleDiscard} disabled={discardDraft.isPending}>
                    {discardDraft.isPending ? 'Discarding...' : 'Discard Draft'}
                  </Button>
                </Box>
                {!hasRole('admin') && (
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                    Only admins can promote to production.
                  </Typography>
                )}
              </StepContent>
            </Step>

            {/* Step 3: Done */}
            <Step>
              <StepLabel><Typography variant="subtitle1" fontWeight={600}>✅ Complete</Typography></StepLabel>
              <StepContent>
                <Alert severity="success">
                  {promoteMessage || 'Draft promoted to production. The fix is live.'}
                </Alert>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  Production runs on the <strong>production</strong> endpoint — invoke it with
                  qualifier <code>production</code>. The DEFAULT endpoint always tracks the latest version.
                </Typography>
                <Box display="flex" gap={2} mt={2}>
                  <Button variant="contained" onClick={() => navigate('/errors')}>Back to Error Analysis</Button>
                </Box>
              </StepContent>
            </Step>
          </Stepper>
        </Paper>
      </Box>
    </Container>
  );
};
