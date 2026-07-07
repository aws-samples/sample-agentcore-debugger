import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import { CssBaseline, Box, CircularProgress, Typography } from '@mui/material';
import { MainLayout } from './components/layout/MainLayout';
import { Dashboard } from './pages/Dashboard';
import { ErrorAnalysis } from './pages/ErrorAnalysis';
import { AgentsPage } from './pages/AgentsPage';
import { FixWorkflow } from './pages/FixWorkflow';
import { TestLocally } from './pages/TestLocally';
import { Settings } from './pages/Settings';
import { AgentDetails } from './pages/AgentDetails';
import { TestErrors } from './pages/TestErrors';
import { Login } from './pages/Login';
import { AuthCallback } from './pages/AuthCallback';
import { useAuthStore } from './stores/authStore';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#1976d2' },
    secondary: { main: '#dc004e' },
  },
});

/**
 * Auth-aware wrapper. Shows a loading spinner while auth initializes,
 * the login page when unauthenticated, or the app when authenticated.
 */
const AuthGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, isLoading, isInitialized, authConfig, initialize } = useAuthStore();

  useEffect(() => {
    if (!isInitialized) initialize();
  }, [isInitialized, initialize]);

  if (isLoading || !isInitialized) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <CircularProgress sx={{ mr: 2 }} />
        <Typography>Loading…</Typography>
      </Box>
    );
  }

  // Auth disabled (dev mode) or user is authenticated → show app
  if (!authConfig?.auth_enabled || user) {
    return <>{children}</>;
  }

  // Not authenticated → show login
  return <Login />;
};

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/auth/callback" element={<AuthCallback />} />

            {/* Protected routes */}
            <Route
              path="/"
              element={
                <AuthGate>
                  <MainLayout />
                </AuthGate>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="agents/:agentId" element={<AgentDetails />} />
              <Route path="errors" element={<ErrorAnalysis />} />
              <Route path="test-errors" element={<TestErrors />} />
              <Route path="fix" element={<FixWorkflow />} />
              <Route path="test" element={<TestLocally />} />
              <Route path="settings" element={<Settings />} />
            </Route>

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
