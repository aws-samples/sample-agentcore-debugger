/**
 * Login page — shown when auth is enabled and user is not authenticated.
 */
import React from 'react';
import { Box, Button, Typography, Paper, Alert } from '@mui/material';
import { Login as LoginIcon } from '@mui/icons-material';
import { useAuthStore } from '../stores/authStore';

export const Login: React.FC = () => {
  const { login, error, clearError } = useAuthStore();

  return (
    <Box
      display="flex"
      justifyContent="center"
      alignItems="center"
      minHeight="100vh"
      bgcolor="grey.100"
    >
      <Paper sx={{ p: 5, maxWidth: 420, textAlign: 'center' }}>
        <Typography variant="h4" gutterBottom>
          AgentCore Debugger
        </Typography>
        <Typography variant="body1" color="text.secondary" mb={3}>
          Sign in with your corporate SSO to continue.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={clearError}>
            {error}
          </Alert>
        )}

        <Button
          variant="contained"
          size="large"
          startIcon={<LoginIcon />}
          onClick={login}
          fullWidth
        >
          Sign In with SSO
        </Button>
      </Paper>
    </Box>
  );
};
