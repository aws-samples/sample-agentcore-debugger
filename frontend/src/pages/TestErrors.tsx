/**
 * Test Errors page - Generate test errors to try out the debugging workflow
 */
import React from 'react';
import { Box, Typography, Paper } from '@mui/material';
import { TestErrorGenerator } from '../components/TestErrorGenerator';

export const TestErrors: React.FC = () => {
  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Test Errors
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
        Generate test errors to try out the debugging workflow
      </Typography>
      
      <Paper sx={{ p: 3 }}>
        <TestErrorGenerator />
      </Paper>
    </Box>
  );
};
