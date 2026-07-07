/**
 * Sample (demo) agent card.
 *
 * Lets users deploy a bundled, intentionally-buggy sample agent so they can try
 * the debugger end-to-end before pointing it at their real agents. Deployment is
 * async on the backend (packaging + arm64 deps + runtime READY takes minutes), so
 * we kick it off and poll /test-agent/build-status to avoid gateway timeouts.
 */
import React, { useEffect, useState } from 'react';
import {
  Box, Paper, Typography, Button, Alert, Chip, LinearProgress, CircularProgress,
  Accordion, AccordionSummary, AccordionDetails,
} from '@mui/material';
import { Science, CheckCircle, Error as ErrorIcon, RocketLaunch, ExpandMore } from '@mui/icons-material';
import { useDeploySample, useSampleStatus, useBuildStatus } from '../../hooks/useTestAgent';

const PHASE_PROGRESS: Record<string, number> = {
  preparing: 10, packaging: 30, uploading: 45, deploying: 75, ready: 100, failed: 0,
};

export const SampleAgentCard: React.FC = () => {
  const { data: sampleStatus, refetch: refetchSample } = useSampleStatus();
  const deploySample = useDeploySample();
  const [buildId, setBuildId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: build } = useBuildStatus(buildId, { enabled: !!buildId });

  useEffect(() => {
    if (!build) return;
    if (build.status === 'ready') {
      setBuildId(null);
      refetchSample();
    } else if (build.status === 'failed') {
      setBuildId(null);
      setError(build.message || 'Sample deployment failed');
    }
  }, [build, refetchSample]);

  const handleDeploy = async () => {
    setError(null);
    try {
      const res = await deploySample.mutateAsync();
      if (res.status === 'started' && res.build_id) {
        setBuildId(res.build_id);
      } else if (res.status === 'failed') {
        setError(res.error || res.message || 'Failed to start sample deployment');
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to start sample deployment');
    }
  };

  const deploying = !!buildId;
  const phase = build?.status || '';
  const progress = PHASE_PROGRESS[phase] ?? 0;
  const isDeployed = sampleStatus?.deployed && sampleStatus?.status === 'READY';

  return (
    <Paper variant="outlined" sx={{ p: 2.5, mb: 3, bgcolor: 'grey.50' }}>
      <Box display="flex" alignItems="center" gap={1} mb={1}>
        <Science color="primary" />
        <Typography variant="h6">Try a sample agent</Typography>
        {isDeployed && (
          <Chip size="small" color="success" icon={<CheckCircle />} label="Deployed" />
        )}
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Deploy a bundled, intentionally-buggy demo agent to try the full
        analyze → fix → draft → test → promote flow without touching your real agents.
      </Typography>

      <Accordion
        disableGutters
        elevation={0}
        sx={{ mb: 2, bgcolor: 'transparent', '&:before': { display: 'none' } }}
      >
        <AccordionSummary expandIcon={<ExpandMore />} sx={{ px: 0, minHeight: 0 }}>
          <Typography variant="body2" color="primary">
            Example prompts &amp; the errors they trigger
          </Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pt: 0 }}>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Invoke the agent with one of these prompts to trigger an error, then let the debugger
            fix it — after deploying the fix, the same prompt returns the correct response.
          </Typography>
          <Box component="ul" sx={{ pl: 2.5, m: 0, '& li': { mb: 0.75 } }}>
            <Typography component="li" variant="body2" color="text.secondary">
              <code>"Show me my order history"</code> → <strong>AttributeError</strong> from pandas
              <code> df.append</code> (removed in pandas 2.x). Fixed → returns the 3 orders and order total.
            </Typography>
            <Typography component="li" variant="body2" color="text.secondary">
              <code>"What is my customer score"</code> → <strong>AttributeError</strong> from numpy
              <code> np.int</code> (removed in NumPy 1.24+). Fixed → returns the customer score and tier.
            </Typography>
            <Typography component="li" variant="body2" color="text.secondary">
              <code>"Please test the module"</code> → <strong>ZeroDivisionError</strong> (division by zero in a
              helper). Fixed → returns the calculation result.
            </Typography>
            <Typography component="li" variant="body2" color="text.secondary">
              <code>"Check the service status"</code> → <strong>ConnectionError</strong> (external API call with no
              retry/timeout handling). Fixed → returns the service status.
            </Typography>
          </Box>
        </AccordionDetails>
      </Accordion>

      {deploying && build && (
        <Box sx={{ mb: 2 }}>
          <Box display="flex" alignItems="center" gap={1} mb={0.5}>
            <CircularProgress size={16} />
            <Typography variant="body2">{build.message || 'Deploying sample agent...'}</Typography>
          </Box>
          <LinearProgress variant="determinate" value={progress} />
        </Box>
      )}

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      {isDeployed && !deploying && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Sample agent <strong>{sampleStatus?.agent_name}</strong> is ready
          ({sampleStatus?.agent_id}). Invoke it from the agent list, then debug it.
          Re-deploying resets it to the original buggy code.
        </Alert>
      )}

      <Button
        variant="contained"
        startIcon={deploying ? <CircularProgress size={18} /> : <RocketLaunch />}
        onClick={handleDeploy}
        disabled={deploying || deploySample.isPending}
      >
        {deploying ? 'Deploying...' : isDeployed ? 'Reset / Redeploy Sample' : 'Deploy Sample Agent'}
      </Button>
    </Paper>
  );
};
