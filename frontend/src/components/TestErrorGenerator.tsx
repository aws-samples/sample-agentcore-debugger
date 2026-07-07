/**
 * Test Error Generator Component
 * Allows users to generate test errors for the test-customer-agent
 */
import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Typography,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  CircularProgress,
  Tooltip,
  Chip,
} from '@mui/material';
import {
  BugReport as BugIcon,
  Science as TestIcon,
  Info as InfoIcon,
} from '@mui/icons-material';
import { agentApi } from '../api/agents';

const ERROR_TYPES = [
  {
    value: 'order',
    label: 'Pandas Deprecation',
    description: 'Triggers df.append() deprecation error',
    prompt: 'Show me my order history',
  },
  {
    value: 'score',
    label: 'NumPy Deprecation',
    description: 'Triggers np.int deprecation error',
    prompt: 'What is my customer score?',
  },
  {
    value: 'recommend',
    label: 'PyTorch Error',
    description: 'Triggers invalid ord parameter error',
    prompt: 'Can you recommend products?',
  },
  {
    value: 'status',
    label: 'Connection Error',
    description: 'Triggers requests connection error',
    prompt: 'Check service status',
  },
  {
    value: 'module',
    label: 'Module Exception',
    description: 'Triggers imported module exception',
    prompt: 'Test the module',
  },
];

interface DeployedAgent {
  name: string;
  arn: string;
  id: string;
  status: string;
}

interface TestErrorGeneratorProps {
  agentId?: string;
}

export const TestErrorGenerator: React.FC<TestErrorGeneratorProps> = ({ agentId }) => {
  const [errorType, setErrorType] = useState<string>('order');
  const [loading, setLoading] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [result, setResult] = useState<{ status: string; message: string } | null>(null);
  const [deployedAgents, setDeployedAgents] = useState<DeployedAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<DeployedAgent | null>(null);

  // Fetch deployed agents on mount - only show test_customer_agent
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const response = await agentApi.listDeployedAgents('us-east-1');
        // Filter to only show test_customer_agent (the one with intentional bugs)
        const testAgent = response.agents.find(a => 
          a.name.toLowerCase().includes('test_customer') || 
          a.name.toLowerCase().includes('test-customer')
        );
        if (testAgent) {
          setDeployedAgents([testAgent]);
          setSelectedAgent(testAgent);
        } else {
          setDeployedAgents([]);
        }
      } catch (error) {
        console.error('Failed to fetch deployed agents:', error);
      } finally {
        setLoadingAgents(false);
      }
    };
    fetchAgents();
  }, []);

  const handleGenerate = async () => {
    if (!selectedAgent) {
      setResult({ status: 'error', message: 'Please select an agent first' });
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      const response = await agentApi.generateTestError(
        selectedAgent.id,
        errorType as 'order' | 'score' | 'recommend' | 'status' | 'module',
        selectedAgent.arn  // Pass the actual ARN
      );
      setResult({
        status: response.status,
        message: response.message,
      });
    } catch (error) {
      setResult({
        status: 'error',
        message: error instanceof Error ? error.message : 'Failed to generate error',
      });
    } finally {
      setLoading(false);
    }
  };

  const selectedError = ERROR_TYPES.find((e) => e.value === errorType);

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
          <TestIcon color="warning" />
          <Typography variant="h6">Generate Test Errors</Typography>
          <Tooltip title="Invoke a deployed agent with prompts that trigger intentional bugs. Use this to test the error analysis and auto-fix workflow.">
            <InfoIcon fontSize="small" color="action" sx={{ cursor: 'help' }} />
          </Tooltip>
        </Box>

        {/* Agent Status */}
        {loadingAgents ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
            <CircularProgress size={16} />
            <Typography variant="body2">Looking for test_customer_agent...</Typography>
          </Box>
        ) : deployedAgents.length === 0 ? (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <strong>test_customer_agent</strong> not found in Amazon Bedrock AgentCore. 
            This is the agent with intentional bugs for testing the debugging workflow.
            Please deploy it first using the AgentCore toolkit.
          </Alert>
        ) : null}

        {selectedAgent && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Generate errors in <Chip label={selectedAgent.name} size="small" color="primary" /> to test
            the debugging workflow.
          </Typography>
        )}

        <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Error Type</InputLabel>
            <Select
              value={errorType}
              label="Error Type"
              onChange={(e) => setErrorType(e.target.value)}
            >
              {ERROR_TYPES.map((type) => (
                <MenuItem key={type.value} value={type.value}>
                  {type.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Button
            variant="contained"
            color="warning"
            startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <BugIcon />}
            onClick={handleGenerate}
            disabled={loading || !selectedAgent}
          >
            {loading ? 'Invoking...' : 'Generate Error'}
          </Button>
        </Box>

        {selectedError && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Prompt: "{selectedError.prompt}" → {selectedError.description}
          </Typography>
        )}

        {result && (
          <Alert
            severity={result.status === 'invoked' ? 'success' : 'error'}
            sx={{ mt: 2 }}
          >
            {result.message}
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};
