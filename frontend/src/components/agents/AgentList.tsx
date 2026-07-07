/**
 * Agent list component
 */
import React, { useState } from 'react';
import {
  Box,
  Typography,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Pagination,
  Paper,
  Chip,
  CircularProgress,
  Alert,
  AlertTitle,
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useAgents } from '../../hooks/useAgents';
import { useAppStore } from '../../stores/appStore';
import { AgentCard } from './AgentCard';
import { Agent, AgentStatus, AgentSource } from '../../types/agent';

export const AgentList: React.FC = () => {
  const navigate = useNavigate();
  const { agentFilters, setAgentFilters, setSelectedAgent } = useAppStore();
  const [page, setPage] = useState(1);
  const itemsPerPage = 12;

  // Calculate offset based on page
  const offset = (page - 1) * itemsPerPage;
  const filters = { ...agentFilters, limit: itemsPerPage, offset };

  const { data, isLoading, error } = useAgents(filters);

  const handleSearchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setAgentFilters({ ...agentFilters, search: event.target.value });
    setPage(1);
  };

  const handleStatusChange = (event: any) => {
    setAgentFilters({ ...agentFilters, status: event.target.value || undefined });
    setPage(1);
  };

  const handleSourceChange = (event: any) => {
    setAgentFilters({ ...agentFilters, source: event.target.value || undefined });
    setPage(1);
  };

  const handlePageChange = (_: React.ChangeEvent<unknown>, value: number) => {
    setPage(value);
  };

  const handleAgentClick = (agent: Agent) => {
    setSelectedAgent(agent);
    navigate(`/agents/${agent.agent_id}`);
  };

  const handleViewDetails = (agent: Agent) => {
    setSelectedAgent(agent);
    navigate(`/agents/${agent.agent_id}`);
  };

  if (isLoading) {
    return (
      <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" p={4}>
        <CircularProgress />
        <Typography variant="body2" color="textSecondary" sx={{ mt: 2 }}>
          Loading agents...
        </Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Box p={2}>
        <Alert severity="error">
          <AlertTitle>Failed to load agents</AlertTitle>
          {error.message}
        </Alert>
      </Box>
    );
  }

  const totalPages = Math.ceil((data?.total || 0) / itemsPerPage);

  return (
    <Box>
      {/* Header with metrics */}
      <Box mb={3}>
        {data && (
          <Box display="flex" gap={2} mb={2}>
            <Chip label={`Total: ${data.total}`} color="primary" />
            <Chip label={`Active: ${data.active}`} color="success" />
            <Chip label={`Errors: ${data.errors}`} color="error" />
            <Chip label={`Runtime: ${data.runtime_count}`} color="info" />
          </Box>
        )}
      </Box>

      {/* Filters */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
          <Box sx={{ flex: '1 1 30%', minWidth: 200 }}>
            <TextField
              fullWidth
              label="Search agents"
              placeholder="Search by name or ID..."
              value={agentFilters.search || ''}
              onChange={handleSearchChange}
            />
          </Box>
          <Box sx={{ flex: '1 1 30%', minWidth: 200 }}>
            <FormControl fullWidth>
              <InputLabel>Status</InputLabel>
              <Select
                value={agentFilters.status || ''}
                onChange={handleStatusChange}
                label="Status"
              >
                <MenuItem value="">All Statuses</MenuItem>
                {Object.values(AgentStatus).map((status) => (
                  <MenuItem key={status} value={status}>
                    {status}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
          <Box sx={{ flex: '1 1 30%', minWidth: 200 }}>
            <FormControl fullWidth>
              <InputLabel>Source</InputLabel>
              <Select
                value={agentFilters.source || ''}
                onChange={handleSourceChange}
                label="Source"
              >
                <MenuItem value="">All Sources</MenuItem>
                {Object.values(AgentSource).map((source) => (
                  <MenuItem key={source} value={source}>
                    {source}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
        </Box>
      </Paper>

      {/* Agent grid */}
      {data?.agents && data.agents.length > 0 ? (
        <>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
            {/* Sort agents to show test_customer_agent first */}
            {[...data.agents].sort((a, b) => {
              const priorityAgent = 'test_customer_agent';
              const aIsPriority = a.name?.includes(priorityAgent) || a.agent_id?.includes(priorityAgent);
              const bIsPriority = b.name?.includes(priorityAgent) || b.agent_id?.includes(priorityAgent);
              if (aIsPriority && !bIsPriority) return -1;
              if (!aIsPriority && bIsPriority) return 1;
              return 0;
            }).map((agent) => (
              <Box key={agent.agent_id} sx={{ flex: '1 1 280px', maxWidth: 350 }}>
                <AgentCard
                  agent={agent}
                  onClick={handleAgentClick}
                  onViewDetails={handleViewDetails}
                />
              </Box>
            ))}
          </Box>

          {/* Pagination */}
          {totalPages > 1 && (
            <Box display="flex" justifyContent="center" mt={4}>
              <Pagination
                count={totalPages}
                page={page}
                onChange={handlePageChange}
                color="primary"
                size="large"
              />
            </Box>
          )}
        </>
      ) : (
        <Box textAlign="center" py={4}>
          <Typography variant="h6" color="textSecondary">
            No agents found
          </Typography>
          <Typography variant="body2" color="textSecondary">
            Try adjusting your search filters
          </Typography>
        </Box>
      )}
    </Box>
  );
};
