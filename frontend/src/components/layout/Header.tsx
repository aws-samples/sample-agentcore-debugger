/**
 * Header component with user info and logout
 */
import React from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Box,
  Switch,
  FormControlLabel,
  Button,
  Chip,
  Tooltip,
} from '@mui/material';
import { Menu, Refresh, AddCircleOutline, Logout, Person } from '@mui/icons-material';
import { useAppStore } from '../../stores/appStore';
import { useAuthStore } from '../../stores/authStore';
import { useQueryClient } from '@tanstack/react-query';
import { useWorkflowStore } from '../../stores/workflowStore';
import { useNavigate } from 'react-router-dom';

interface HeaderProps {
  onMenuClick: () => void;
}

const roleBadgeColor: Record<string, 'default' | 'primary' | 'warning' | 'error'> = {
  viewer: 'default',
  operator: 'primary',
  admin: 'error',
};

export const Header: React.FC<HeaderProps> = ({ onMenuClick }) => {
  const { autoRefresh, setAutoRefresh } = useAppStore();
  const { user, logout, authConfig } = useAuthStore();
  const queryClient = useQueryClient();
  const resetWorkflow = useWorkflowStore((state) => state.resetWorkflow);
  const navigate = useNavigate();

  const handleRefresh = () => {
    queryClient.invalidateQueries();
  };

  const handleNewSession = () => {
    resetWorkflow();
    queryClient.clear();
    navigate('/');
  };

  const topRole = user?.roles?.includes('admin')
    ? 'admin'
    : user?.roles?.includes('operator')
      ? 'operator'
      : 'viewer';

  return (
    <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar>
        <IconButton color="inherit" edge="start" onClick={onMenuClick} sx={{ mr: 2 }}>
          <Menu />
        </IconButton>

        <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
          AgentCore Debugger
        </Typography>

        <Box display="flex" alignItems="center" gap={2}>
          <Button
            variant="outlined"
            color="inherit"
            size="small"
            startIcon={<AddCircleOutline />}
            onClick={handleNewSession}
            sx={{ borderColor: 'rgba(255,255,255,0.5)' }}
          >
            New Session
          </Button>

          <FormControlLabel
            control={
              <Switch
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                color="default"
              />
            }
            label="Auto-refresh"
            sx={{ color: 'white' }}
          />

          <IconButton color="inherit" onClick={handleRefresh}>
            <Refresh />
          </IconButton>

          {/* User info */}
          {user && (
            <Box display="flex" alignItems="center" gap={1}>
              <Tooltip title={user.email}>
                <Chip
                  icon={<Person />}
                  label={user.username}
                  size="small"
                  sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.5)' }}
                  variant="outlined"
                />
              </Tooltip>
              <Chip
                label={topRole}
                size="small"
                color={roleBadgeColor[topRole]}
              />
              {authConfig?.auth_enabled && (
                <Tooltip title="Sign out">
                  <IconButton color="inherit" onClick={logout} size="small">
                    <Logout fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          )}
        </Box>
      </Toolbar>
    </AppBar>
  );
};
