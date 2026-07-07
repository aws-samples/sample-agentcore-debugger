/**
 * OAuth2 callback handler — exchanges the authorization code for tokens.
 * Waits for auth store to initialize before attempting token exchange.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Box, CircularProgress, Typography, Alert, Button } from '@mui/material';
import { useAuthStore } from '../stores/authStore';

export const AuthCallback: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { handleCallback, initialize, isInitialized, authConfig } = useAuthStore();
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);

  // Ensure auth is initialized first
  useEffect(() => {
    if (!isInitialized) initialize();
  }, [isInitialized, initialize]);

  // Once initialized, exchange the code
  useEffect(() => {
    if (!isInitialized || !authConfig || processing) return;

    const code = searchParams.get('code');
    const errorParam = searchParams.get('error');
    const errorDesc = searchParams.get('error_description');

    if (errorParam) {
      setError(`${errorParam}: ${errorDesc || 'Unknown error'}`);
      return;
    }

    if (!code) {
      navigate('/login', { replace: true });
      return;
    }

    setProcessing(true);
    handleCallback(code)
      .then(() => {
        const user = useAuthStore.getState().user;
        if (user) {
          navigate('/', { replace: true });
        } else {
          setError('Token exchange completed but no user was set. Check browser console.');
        }
      })
      .catch((e) => {
        setError(e?.message || 'Authentication failed');
      });
  }, [isInitialized, authConfig]);

  if (error) {
    return (
      <Box display="flex" flexDirection="column" justifyContent="center" alignItems="center" minHeight="100vh" gap={2}>
        <Alert severity="error" sx={{ maxWidth: 500 }}>{error}</Alert>
        <Button variant="contained" onClick={() => navigate('/login', { replace: true })}>
          Back to Login
        </Button>
      </Box>
    );
  }

  return (
    <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
      <CircularProgress sx={{ mr: 2 }} />
      <Typography>Completing sign-in…</Typography>
    </Box>
  );
};
