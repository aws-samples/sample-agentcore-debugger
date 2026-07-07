/**
 * Agents page
 */
import React from 'react';
import { Box, Container, Typography } from '@mui/material';
import { AgentList } from '../components/agents/AgentList';
import { SampleAgentCard } from '../components/agents/SampleAgentCard';

export const AgentsPage: React.FC = () => {
  return (
    <Container maxWidth="xl">
      <Box py={3}>
        <Typography variant="h4" gutterBottom>
          Agents
        </Typography>
        <Typography variant="subtitle1" color="textSecondary" gutterBottom>
          View and manage your Amazon Bedrock AgentCore agents
        </Typography>
        <Box mt={4}>
          <SampleAgentCard />
          <AgentList />
        </Box>
      </Box>
    </Container>
  );
};
