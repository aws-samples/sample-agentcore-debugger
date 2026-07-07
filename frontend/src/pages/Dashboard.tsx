/**
 * Dashboard page - Main entry point
 * Shows what the app does and guides users to get started
 */
import React from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Chip,
  CircularProgress,
  Card,
  CardContent,
  CardActionArea,
  Alert,
  Button,
  Divider,
} from '@mui/material';
import {
  SmartToy,
  Error as ErrorIcon,
  Build,
  PlayArrow,
  CloudUpload,
  CheckCircle,
  ArrowForward,
  AutoFixHigh,
  Code,
  Inventory,
  RocketLaunch,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useAgents } from '../hooks/useAgents';
import { useErrorAnalysis } from '../hooks/useErrors';
import { useWorkflowStore } from '../stores/workflowStore';

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { data: agentsData, isLoading: agentsLoading } = useAgents({ limit: 10 });
  const { data: errorData, isLoading: errorsLoading } = useErrorAnalysis();
  
  const {
    selectedAgentId,
    selectedAgentName,
    fixedPatterns,
    resetWorkflow,
  } = useWorkflowStore();

  // Features of the app
  const features = [
    {
      icon: <ErrorIcon color="error" />,
      title: 'Error Detection',
      description: 'Automatically discovers and clusters error patterns from CloudWatch logs',
    },
    {
      icon: <AutoFixHigh color="primary" />,
      title: 'AI Classification',
      description: 'Classifies errors as package issues, code bugs, or mixed problems',
    },
    {
      icon: <Inventory color="info" />,
      title: 'Library Agent',
      description: 'Analyzes package dependencies and recommends version updates',
    },
    {
      icon: <Code color="warning" />,
      title: 'Code Agent',
      description: 'Downloads the agent code (from ECR or S3) and applies intelligent fixes',
    },
    {
      icon: <PlayArrow color="secondary" />,
      title: 'Draft Testing',
      description: 'Deploy the fix to a draft endpoint and test it before going live',
    },
    {
      icon: <RocketLaunch color="success" />,
      title: 'Promote to Production',
      description: 'Validate the draft, then promote it to the production endpoint',
    },
  ];

  return (
    <Container maxWidth="xl">
      <Box py={3}>
        {/* Hero Section */}
        <Paper 
          sx={{ 
            p: 4, 
            mb: 4, 
            background: 'linear-gradient(135deg, #1976d2 0%, #1565c0 100%)',
            color: 'white',
          }}
        >
          <Box display="flex" alignItems="center" gap={2} mb={2}>
            <SmartToy sx={{ fontSize: 48 }} />
            <Box>
              <Typography variant="h4" fontWeight={700}>
                AgentCore Debugger
              </Typography>
              <Typography variant="subtitle1" sx={{ opacity: 0.9 }}>
                AI-powered debugging for Amazon Bedrock AgentCore
              </Typography>
            </Box>
          </Box>
          
          <Typography variant="body1" sx={{ mb: 3, maxWidth: 700 }}>
            Automatically detect, analyze, and fix errors in your AgentCore agents. 
            Our AI agents classify issues, suggest fixes, and can apply them directly to your code.
          </Typography>
          
          <Button
            variant="contained"
            size="large"
            sx={{ 
              bgcolor: 'white', 
              color: 'primary.main',
              '&:hover': { bgcolor: 'grey.100' },
            }}
            endIcon={<ArrowForward />}
            onClick={() => navigate('/agents')}
          >
            Get Started - View Agents
          </Button>
        </Paper>

        {/* Active Session Banner */}
        {selectedAgentId && (
          <Alert 
            severity="info" 
            sx={{ mb: 3 }}
            action={
              <Button 
                color="inherit" 
                size="small" 
                onClick={() => navigate(`/agents/${selectedAgentId}`)}
              >
                Continue <ArrowForward sx={{ ml: 0.5, fontSize: 16 }} />
              </Button>
            }
          >
            <strong>Active Session:</strong> Working on {selectedAgentName}
            {fixedPatterns.length > 0 && ` • ${fixedPatterns.length} patterns fixed`}
          </Alert>
        )}

        {/* How It Works */}
        <Paper sx={{ p: 3, mb: 4 }}>
          <Typography variant="h6" gutterBottom fontWeight={600}>
            How It Works
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            A simple 4-step workflow to fix your agent errors
          </Typography>
          
          <Box 
            display="flex" 
            gap={2} 
            sx={{ 
              overflowX: 'auto',
              pb: 1,
            }}
          >
            {[
              { step: 1, title: 'Select Agent', desc: 'Choose an agent from your deployed agents', icon: <SmartToy /> },
              { step: 2, title: 'Review Errors', desc: 'See error patterns with AI classification', icon: <ErrorIcon /> },
              { step: 3, title: 'Apply Fixes', desc: 'One-click fix or choose approach for mixed issues', icon: <Build /> },
              { step: 4, title: 'Test & Promote', desc: 'Deploy the fix as a draft, test it, then promote to production', icon: <CloudUpload /> },
            ].map((item, index) => (
              <Card
                key={item.step}
                variant="outlined"
                sx={{
                  minWidth: 200,
                  flex: '1 0 200px',
                  position: 'relative',
                }}
              >
                <CardContent>
                  <Box display="flex" alignItems="center" gap={1} mb={1}>
                    <Chip
                      label={item.step}
                      size="small"
                      color="primary"
                      sx={{ minWidth: 28, height: 28, fontWeight: 700 }}
                    />
                    <Box color="primary.main">{item.icon}</Box>
                  </Box>
                  <Typography variant="subtitle2" fontWeight={600}>
                    {item.title}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {item.desc}
                  </Typography>
                </CardContent>
                {index < 3 && (
                  <ArrowForward 
                    sx={{ 
                      position: 'absolute', 
                      right: -12, 
                      top: '50%', 
                      transform: 'translateY(-50%)',
                      color: 'grey.400',
                      zIndex: 1,
                      display: { xs: 'none', md: 'block' },
                    }} 
                  />
                )}
              </Card>
            ))}
          </Box>
        </Paper>

        {/* Stats Row */}
        <Box display="flex" gap={3} mb={4} flexWrap="wrap">
          {/* Agents Card */}
          <Card
            variant="outlined"
            sx={{ flex: '1 1 200px', minWidth: 200, cursor: 'pointer' }}
            onClick={() => navigate('/agents')}
          >
            <CardActionArea>
              <CardContent>
                <Box display="flex" alignItems="center" gap={1} mb={1}>
                  <SmartToy color="primary" />
                  <Typography variant="subtitle2">Deployed Agents</Typography>
                </Box>
                {agentsLoading ? (
                  <CircularProgress size={24} />
                ) : agentsData ? (
                  <Box>
                    <Typography variant="h3" fontWeight={700}>
                      {agentsData.total}
                    </Typography>
                    <Box display="flex" gap={1} mt={1} flexWrap="wrap">
                      <Chip label={`${agentsData.active} active`} size="small" color="success" />
                      {agentsData.errors > 0 && (
                        <Chip label={`${agentsData.errors} with errors`} size="small" color="error" />
                      )}
                    </Box>
                  </Box>
                ) : (
                  <Typography color="text.secondary">No agents found</Typography>
                )}
              </CardContent>
            </CardActionArea>
          </Card>

          {/* Errors Card */}
          <Card
            variant="outlined"
            sx={{ flex: '1 1 200px', minWidth: 200, cursor: 'pointer' }}
            onClick={() => navigate('/errors')}
          >
            <CardActionArea>
              <CardContent>
                <Box display="flex" alignItems="center" gap={1} mb={1}>
                  <ErrorIcon color="error" />
                  <Typography variant="subtitle2">Total Errors (24h)</Typography>
                </Box>
                {errorsLoading ? (
                  <CircularProgress size={24} />
                ) : errorData ? (
                  <Box>
                    <Typography variant="h3" fontWeight={700} color={errorData.total_errors > 0 ? 'error.main' : 'success.main'}>
                      {errorData.total_errors}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {errorData.error_rate}/hr error rate
                    </Typography>
                  </Box>
                ) : (
                  <Typography color="text.secondary">No data</Typography>
                )}
              </CardContent>
            </CardActionArea>
          </Card>

          {/* Session Fixes Card */}
          <Card
            variant="outlined"
            sx={{ flex: '1 1 200px', minWidth: 200 }}
          >
            <CardContent>
              <Box display="flex" alignItems="center" gap={1} mb={1}>
                <Build color="warning" />
                <Typography variant="subtitle2">Session Fixes</Typography>
              </Box>
              <Typography variant="h3" fontWeight={700}>
                {fixedPatterns.length}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                patterns fixed this session
              </Typography>
            </CardContent>
          </Card>
        </Box>

        {/* Features Grid */}
        <Paper sx={{ p: 3, mb: 4 }}>
          <Typography variant="h6" gutterBottom fontWeight={600}>
            Features
          </Typography>
          <Box 
            display="grid" 
            gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' }}
            gap={2}
          >
            {features.map((feature, index) => (
              <Box key={index} display="flex" gap={2} p={2} bgcolor="grey.50" borderRadius={1}>
                <Box>{feature.icon}</Box>
                <Box>
                  <Typography variant="subtitle2" fontWeight={600}>
                    {feature.title}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {feature.description}
                  </Typography>
                </Box>
              </Box>
            ))}
          </Box>
        </Paper>

        {/* Quick Actions */}
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom fontWeight={600}>
            Quick Actions
          </Typography>
          <Box display="flex" gap={2} flexWrap="wrap">
            <Button
              variant="contained"
              startIcon={<SmartToy />}
              onClick={() => navigate('/agents')}
            >
              View Agents
            </Button>
            {selectedAgentId && fixedPatterns.length > 0 && (
              <Button
                variant="contained"
                color="warning"
                startIcon={<Build />}
                onClick={() => navigate(`/agents/${selectedAgentId}`)}
              >
                Continue Fixing {selectedAgentName} ({fixedPatterns.length} fixed)
              </Button>
            )}
            <Button
              variant="outlined"
              color="error"
              startIcon={<ErrorIcon />}
              onClick={() => navigate('/errors')}
            >
              Error Analysis
            </Button>
            {fixedPatterns.length > 0 && (
              <Button
                variant="outlined"
                color="info"
                startIcon={<PlayArrow />}
                onClick={() => navigate('/test')}
              >
                Test on AWS
              </Button>
            )}
          </Box>
        </Paper>


      </Box>
    </Container>
  );
};
