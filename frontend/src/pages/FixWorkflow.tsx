/**
 * Fix Workflow Page
 * Redirects to Agent Details page where fix workflow is now integrated
 */
import React, { useEffect } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Button,
  Alert,
} from '@mui/material';
import {
  ArrowForward,
  SmartToy,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useWorkflowStore } from '../stores/workflowStore';

export const FixWorkflow: React.FC = () => {
  const navigate = useNavigate();
  const { selectedAgentId, selectedAgentName } = useWorkflowStore();

  // If an agent is already selected, redirect to Error Analysis page
  useEffect(() => {
    if (selectedAgentId) {
      navigate('/errors');
    }
  }, [selectedAgentId, navigate]);

  return (
    <Container maxWidth="md">
      <Box py={3}>
        <Typography variant="h4" gutterBottom>
          Fix Workflow
        </Typography>
        
        <Paper sx={{ p: 4, mt: 3, textAlign: 'center' }}>
          <SmartToy sx={{ fontSize: 64, color: 'primary.main', mb: 2 }} />
          
          <Typography variant="h6" gutterBottom>
            Fix Workflow is Now Integrated
          </Typography>
          
          <Alert severity="info" sx={{ mb: 3, textAlign: 'left' }}>
            <Typography variant="body2">
              The fix workflow has been integrated directly into the Agent Details page for a smoother experience.
              <br /><br />
              <strong>How to fix errors:</strong>
              <br />
              1. Go to the Agents page
              <br />
              2. Click on an agent to view its details
              <br />
              3. See error patterns with classification
              <br />
              4. Click "Fix All Patterns" or fix individual patterns
              <br />
              5. For mixed errors, choose your fix approach
              <br />
              6. Deploy the fix as a draft, test it, then promote to production
            </Typography>
          </Alert>
          
          <Button
            variant="contained"
            size="large"
            endIcon={<ArrowForward />}
            onClick={() => navigate('/errors')}
          >
            Go to Error Analysis
          </Button>
        </Paper>
      </Box>
    </Container>
  );
};
