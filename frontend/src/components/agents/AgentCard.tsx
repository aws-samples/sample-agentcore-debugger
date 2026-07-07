/**
 * Agent card component
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Chip,
  Box,
  IconButton,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  CircularProgress,
  Alert,
} from '@mui/material';
import {
  CheckCircle,
  Error as ErrorIcon,
  Warning,
  Info,
  Visibility,
  PlayArrow,
  Send,
  Close,
} from '@mui/icons-material';
import { Agent, AgentStatus } from '../../types/agent';
import { agentApi } from '../../api/agents';
import { fixApi } from '../../api/fix';

interface AgentCardProps {
  agent: Agent;
  onClick?: (agent: Agent) => void;
  onViewDetails?: (agent: Agent) => void;
}

const getStatusColor = (status: AgentStatus): 'success' | 'error' | 'warning' | 'default' => {
  switch (status) {
    case AgentStatus.ACTIVE:
    case AgentStatus.PREPARED:
      return 'success';
    case AgentStatus.FAILED:
    case AgentStatus.ERROR:
      return 'error';
    case AgentStatus.CREATING:
    case AgentStatus.UPDATING:
      return 'warning';
    default:
      return 'default';
  }
};

const getStatusIcon = (status: AgentStatus) => {
  switch (status) {
    case AgentStatus.ACTIVE:
    case AgentStatus.PREPARED:
      return <CheckCircle />;
    case AgentStatus.FAILED:
    case AgentStatus.ERROR:
      return <ErrorIcon />;
    case AgentStatus.CREATING:
    case AgentStatus.UPDATING:
      return <Warning />;
    default:
      return <Info />;
  }
};

export const AgentCard: React.FC<AgentCardProps> = ({ 
  agent, 
  onClick, 
  onViewDetails 
}) => {
  // Test dialog state
  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    response?: string;
    parsedResponse?: Record<string, unknown>;
    error?: string;
  } | null>(null);
  const [deployedArn, setDeployedArn] = useState<string | null>(null);
  const [loadingArn, setLoadingArn] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);  // Persist session across invocations
  const [conversationHistory, setConversationHistory] = useState<Array<{
    role: 'user' | 'agent';
    content: string;
    timestamp: string;
  }>>([]);

  // Fetch deployed ARN when dialog opens
  useEffect(() => {
    if (testDialogOpen && !deployedArn) {
      const fetchArn = async () => {
        setLoadingArn(true);
        try {
          const response = await agentApi.listDeployedAgents('us-east-1');
          // Normalize names for matching (handle hyphens, underscores, case)
          const normalizedName = agent.name.toLowerCase().replace(/[-_]/g, '');
          const normalizedId = agent.agent_id?.toLowerCase().replace(/[-_]/g, '') || '';
          
          const matched = response.agents.find(a => {
            const deployedName = a.name.toLowerCase().replace(/[-_]/g, '');
            const deployedId = a.id?.toLowerCase().replace(/[-_]/g, '') || '';
            
            return (
              deployedName === normalizedName ||
              deployedName.includes(normalizedName) ||
              normalizedName.includes(deployedName) ||
              deployedId.includes(normalizedName) ||
              normalizedId.includes(deployedName) ||
              // Also check if agent_id contains the deployed agent name
              normalizedId.includes(deployedName.split(/[-_]/)[0])
            );
          });
          
          if (matched) {
            setDeployedArn(matched.arn);
          } else {
            // Log for debugging
            console.log('No match found. Agent:', agent.name, 'Deployed:', response.agents.map(a => a.name));
          }
        } catch (error) {
          console.error('Failed to fetch deployed ARN:', error);
        } finally {
          setLoadingArn(false);
        }
      };
      fetchArn();
    }
  }, [testDialogOpen, agent.name, deployedArn]);

  const handleCardClick = () => {
    if (onClick) {
      onClick(agent);
    }
  };

  const handleViewDetails = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onViewDetails) {
      onViewDetails(agent);
    }
  };

  const handleTestClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setTestDialogOpen(true);
    setTestResult(null);
    setPrompt('');
    // Don't reset session - keep it for conversation continuity
    // Session resets when dialog closes
  };

  const handleTestAgent = async () => {
    if (!deployedArn || !prompt.trim()) return;
    
    setTesting(true);
    
    // Add user message to history
    const userMessage = prompt;
    setConversationHistory(prev => [...prev, {
      role: 'user' as const,
      content: userMessage,
      timestamp: new Date().toISOString(),
    }]);
    
    try {
      // Pass existing sessionId if we have one (for conversation continuity)
      const result = await fixApi.testDeployedAgent(deployedArn, userMessage, sessionId || undefined);
      
      // Store session ID from response for next call
      if (result.session_id) {
        setSessionId(result.session_id);
      }
      
      // Extract agent response text - show full response, not just the "response" field
      let agentResponse = '';
      if (result.parsed_response) {
        const parsed = result.parsed_response;
        // Handle nested response structure: {"response": {...}, "status": "success"}
        if (typeof parsed.response === 'string') {
          try {
            const inner = JSON.parse(parsed.response);
            // Show full object if it has more than just response/error fields
            if (inner.recommendations || inner.data || Object.keys(inner).length > 2) {
              agentResponse = JSON.stringify(inner, null, 2);
            } else {
              agentResponse = inner.response || inner.error || JSON.stringify(inner, null, 2);
            }
          } catch {
            agentResponse = parsed.response;
          }
        } else if (typeof parsed.response === 'object' && parsed.response !== null) {
          // Response is already an object - show full object
          const respObj = parsed.response as Record<string, unknown>;
          // If it has rich data (recommendations, etc), show full JSON
          if (respObj.recommendations || respObj.data || Object.keys(respObj).length > 2) {
            agentResponse = JSON.stringify(respObj, null, 2);
          } else {
            agentResponse = (respObj.response as string) || (respObj.error as string) || JSON.stringify(respObj, null, 2);
          }
        } else if (typeof parsed === 'string') {
          agentResponse = parsed;
        } else {
          agentResponse = JSON.stringify(parsed, null, 2);
        }
      } else if (result.response) {
        // Try to parse the raw response
        try {
          const parsed = JSON.parse(result.response);
          if (typeof parsed.response === 'string') {
            try {
              const inner = JSON.parse(parsed.response);
              if (inner.recommendations || inner.data || Object.keys(inner).length > 2) {
                agentResponse = JSON.stringify(inner, null, 2);
              } else {
                agentResponse = inner.response || inner.error || JSON.stringify(inner, null, 2);
              }
            } catch {
              agentResponse = parsed.response;
            }
          } else {
            agentResponse = JSON.stringify(parsed, null, 2);
          }
        } catch {
          agentResponse = result.response;
        }
      }
      
      // Add agent response to history
      setConversationHistory(prev => [...prev, {
        role: 'agent' as const,
        content: agentResponse,
        timestamp: new Date().toISOString(),
      }]);
      
      setTestResult({
        success: result.status === 'success',
        response: result.response,
        parsedResponse: result.parsed_response,
        error: result.error,
      });
      setPrompt('');
    } catch (error) {
      setTestResult({
        success: false,
        error: error instanceof Error ? error.message : 'Failed to invoke agent',
      });
    } finally {
      setTesting(false);
    }
  };

  const handleCloseDialog = () => {
    setTestDialogOpen(false);
    setTestResult(null);
    setPrompt('');
    // Reset session and conversation when dialog closes
    setSessionId(null);
    setConversationHistory([]);
  };

  return (
    <>
    <Card
      sx={{
        cursor: onClick ? 'pointer' : 'default',
        '&:hover': onClick ? {
          boxShadow: 3,
          transform: 'translateY(-2px)',
        } : {},
        transition: 'all 0.2s ease-in-out',
      }}
      onClick={handleCardClick}
    >
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={2}>
          <Box flex={1}>
            <Typography variant="h6" component="h3" gutterBottom>
              {agent.name}
            </Typography>
            <Typography variant="body2" color="textSecondary" gutterBottom>
              {agent.agent_id}
            </Typography>
          </Box>
          <Box display="flex" gap={0.5}>
            <Tooltip title="Invoke Agent">
              <IconButton size="small" onClick={handleTestClick} color="primary">
                <PlayArrow />
              </IconButton>
            </Tooltip>
            {onViewDetails && (
              <Tooltip title="View Details">
                <IconButton size="small" onClick={handleViewDetails}>
                  <Visibility />
                </IconButton>
              </Tooltip>
            )}
          </Box>
        </Box>

        <Box display="flex" gap={1} mb={2}>
          <Chip
            icon={getStatusIcon(agent.status)}
            label={agent.status}
            color={getStatusColor(agent.status)}
            size="small"
          />
          <Chip
            label={agent.source}
            variant="outlined"
            size="small"
          />
        </Box>

        {agent.log_group && (
          <Typography variant="body2" color="textSecondary" noWrap>
            Log Group: {agent.log_group}
          </Typography>
        )}

        {agent.stored_bytes && (
          <Typography variant="body2" color="textSecondary">
            Storage: {(agent.stored_bytes / 1024 / 1024).toFixed(2)} MB
          </Typography>
        )}

        {agent.created_at && (
          <Typography variant="body2" color="textSecondary">
            Created: {new Date(agent.created_at).toLocaleDateString()}
          </Typography>
        )}
      </CardContent>
    </Card>

    {/* Invoke Agent Dialog */}
    <Dialog 
      open={testDialogOpen} 
      onClose={handleCloseDialog}
      maxWidth="md"
      fullWidth
      onClick={(e) => e.stopPropagation()}
    >
      <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          ☁️ Invoke Agent: {agent.name}
        </Box>
        <IconButton size="small" onClick={handleCloseDialog}>
          <Close />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {loadingArn ? (
          <Box display="flex" alignItems="center" gap={1} py={2}>
            <CircularProgress size={20} />
            <Typography>Looking for deployed agent...</Typography>
          </Box>
        ) : !deployedArn ? (
          <Alert severity="warning" sx={{ mb: 2 }}>
            This agent is not deployed to Amazon Bedrock AgentCore. Deploy it first to test.
          </Alert>
        ) : (
          <>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Alert severity="info" sx={{ flex: 1 }}>
                Connected to deployed agent.{sessionId && ` Session active.`}
              </Alert>
              {sessionId && (
                <Button 
                  size="small" 
                  onClick={() => { setSessionId(null); setConversationHistory([]); }}
                  sx={{ ml: 1 }}
                >
                  New Session
                </Button>
              )}
            </Box>

            {/* Conversation History */}
            {conversationHistory.length > 0 && (
              <Box sx={{ 
                mb: 2, 
                maxHeight: 300, 
                overflow: 'auto',
                border: '1px solid #e0e0e0',
                borderRadius: 1,
                p: 1,
              }}>
                {conversationHistory.map((msg, idx) => (
                  <Box 
                    key={idx} 
                    sx={{ 
                      mb: 1, 
                      p: 1.5, 
                      borderRadius: 1,
                      bgcolor: msg.role === 'user' ? '#e3f2fd' : '#f5f5f5',
                      borderLeft: msg.role === 'user' ? '3px solid #1976d2' : '3px solid #4caf50',
                    }}
                  >
                    <Typography variant="caption" color="text.secondary" fontWeight={600}>
                      {msg.role === 'user' ? '👤 You' : '🤖 Agent'}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                      {msg.content}
                    </Typography>
                  </Box>
                ))}
              </Box>
            )}
            
            <Box display="flex" gap={2} alignItems="flex-start" mb={2}>
              <TextField
                fullWidth
                label="Enter your prompt"
                placeholder="What can you help me with?"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && !e.shiftKey && handleTestAgent()}
                multiline
                rows={2}
                disabled={testing}
              />
              <Button
                variant="contained"
                startIcon={testing ? <CircularProgress size={20} /> : <Send />}
                onClick={handleTestAgent}
                disabled={!prompt.trim() || testing}
                sx={{ minWidth: 100, height: 56 }}
              >
                {testing ? 'Sending...' : 'Send'}
              </Button>
            </Box>

            {/* Error Display */}
            {testResult && !testResult.success && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {testResult.error || 'Failed to invoke agent'}
              </Alert>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleCloseDialog}>Close</Button>
      </DialogActions>
    </Dialog>
    </>
  );
};
