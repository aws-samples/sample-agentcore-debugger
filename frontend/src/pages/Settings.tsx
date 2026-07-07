/**
 * Settings Page
 * Application configuration + User Management (admin only)
 */
import React, { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  TextField,
  Button,
  Switch,
  FormControlLabel,
  Divider,
  Alert,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Select,
  MenuItem,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
} from '@mui/material';
import { PersonAdd, Delete, Edit } from '@mui/icons-material';
import { useAuthStore } from '../stores/authStore';
import apiClient from '../api/client';

interface ManagedUser {
  username: string;
  email: string;
  role: string;
  status: string;
  enabled: boolean;
  created: string | null;
}

export const Settings: React.FC = () => {
  const { hasRole, user: currentUser } = useAuthStore();
  const isAdmin = hasRole('admin');

  // App settings
  const [settings, setSettings] = useState({
    apiUrl: import.meta.env.VITE_API_URL || 'http://localhost:8000',
    awsRegion: 'us-east-1',
    autoRefresh: true,
    refreshInterval: 30,
  });
  const [saved, setSaved] = useState(false);

  // User management state
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newRole, setNewRole] = useState('viewer');
  const [newPassword, setNewPassword] = useState('');
  const [creating, setCreating] = useState(false);
  const [actionMsg, setActionMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Load users on mount (admin only)
  useEffect(() => {
    if (isAdmin) loadUsers();
  }, [isAdmin]);

  const loadUsers = async () => {
    setUsersLoading(true);
    setUsersError(null);
    try {
      const resp = await apiClient.get('/users/list');
      setUsers(resp.data.users);
    } catch (e: any) {
      setUsersError(e?.response?.data?.detail || 'Failed to load users');
    } finally {
      setUsersLoading(false);
    }
  };

  const handleCreateUser = async () => {
    if (!newEmail) return;
    setCreating(true);
    setActionMsg(null);
    try {
      const resp = await apiClient.post('/users/create', {
        email: newEmail,
        role: newRole,
        temporary_password: newPassword || undefined,
      });
      setActionMsg({ type: 'success', text: resp.data.message });
      setCreateOpen(false);
      setNewEmail('');
      setNewRole('viewer');
      setNewPassword('');
      loadUsers();
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e?.response?.data?.detail || 'Failed to create user' });
    } finally {
      setCreating(false);
    }
  };

  const handleRoleChange = async (email: string, role: string) => {
    setActionMsg(null);
    try {
      await apiClient.put('/users/role', { email, role });
      setActionMsg({ type: 'success', text: `${email} updated to ${role}` });
      loadUsers();
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e?.response?.data?.detail || 'Failed to update role' });
    }
  };

  const handleDeleteUser = async (email: string) => {
    if (!confirm(`Delete user ${email}? This cannot be undone.`)) return;
    setActionMsg(null);
    try {
      await apiClient.delete('/users/delete', { data: { email } });
      setActionMsg({ type: 'success', text: `${email} deleted` });
      loadUsers();
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e?.response?.data?.detail || 'Failed to delete user' });
    }
  };

  const handleSave = () => {
    localStorage.setItem('agentcore-settings', JSON.stringify(settings));
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleChange = (field: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setSettings((prev) => ({
      ...prev,
      [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value,
    }));
  };

  const roleColor = (role: string) => {
    if (role === 'admin') return 'error';
    if (role === 'operator') return 'primary';
    return 'default';
  };

  return (
    <Container maxWidth="md">
      <Box py={3}>
        <Typography variant="h4" gutterBottom>Settings</Typography>

        {saved && <Alert severity="success" sx={{ mb: 3 }}>Settings saved!</Alert>}
        {actionMsg && <Alert severity={actionMsg.type} sx={{ mb: 2 }} onClose={() => setActionMsg(null)}>{actionMsg.text}</Alert>}

        {/* ── User Management (admin only) ──────────────────────── */}
        {isAdmin && (
          <Paper sx={{ p: 3, mt: 2, mb: 3 }}>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
              <Typography variant="h6">User Management</Typography>
              <Button variant="contained" startIcon={<PersonAdd />} onClick={() => setCreateOpen(true)}>
                Add User
              </Button>
            </Box>

            {usersError && <Alert severity="error" sx={{ mb: 2 }}>{usersError}</Alert>}

            {usersLoading ? (
              <Box display="flex" justifyContent="center" p={3}><CircularProgress /></Box>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Email</TableCell>
                      <TableCell>Role</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="right">Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {users.map((u) => (
                      <TableRow key={u.username}>
                        <TableCell>
                          {u.email}
                          {u.email === currentUser?.email && (
                            <Chip label="you" size="small" sx={{ ml: 1 }} />
                          )}
                        </TableCell>
                        <TableCell>
                          <Select
                            value={u.role}
                            size="small"
                            onChange={(e) => handleRoleChange(u.email, e.target.value)}
                            disabled={u.email === currentUser?.email}
                          >
                            <MenuItem value="viewer">viewer</MenuItem>
                            <MenuItem value="operator">operator</MenuItem>
                            <MenuItem value="admin">admin</MenuItem>
                          </Select>
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={u.status}
                            size="small"
                            color={u.status === 'CONFIRMED' ? 'success' : 'warning'}
                          />
                        </TableCell>
                        <TableCell align="right">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDeleteUser(u.email)}
                            disabled={u.email === currentUser?.email}
                          >
                            <Delete fontSize="small" />
                          </IconButton>
                        </TableCell>
                      </TableRow>
                    ))}
                    {users.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={4} align="center">No users found</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            )}

            {/* Create User Dialog */}
            <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
              <DialogTitle>Add New User</DialogTitle>
              <DialogContent>
                <Box display="flex" flexDirection="column" gap={2} mt={1}>
                  <TextField
                    label="Email"
                    type="email"
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                    fullWidth
                    required
                  />
                  <Select value={newRole} onChange={(e) => setNewRole(e.target.value)} fullWidth>
                    <MenuItem value="viewer">Viewer — can view dashboards and errors</MenuItem>
                    <MenuItem value="operator">Operator — can apply fixes and push code</MenuItem>
                    <MenuItem value="admin">Admin — full access including deploy and settings</MenuItem>
                  </Select>
                  <TextField
                    label="Password (optional — auto-generated if empty)"
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    fullWidth
                    helperText="Min 12 chars, uppercase, lowercase, number, symbol"
                  />
                  <Alert severity="info">
                    User will receive an email confirmation and can log in immediately — no password reset required.
                  </Alert>
                </Box>
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
                <Button
                  variant="contained"
                  onClick={handleCreateUser}
                  disabled={!newEmail || creating}
                  startIcon={creating ? <CircularProgress size={16} /> : <PersonAdd />}
                >
                  {creating ? 'Creating...' : 'Create User'}
                </Button>
              </DialogActions>
            </Dialog>
          </Paper>
        )}

        {/* ── App Settings ──────────────────────────────────────── */}
        <Paper sx={{ p: 3, mt: 2 }}>
          <Typography variant="h6" gutterBottom>API Configuration</Typography>
          <Box display="flex" flexDirection="column" gap={2}>
            <TextField fullWidth label="API URL" value={settings.apiUrl} onChange={handleChange('apiUrl')} />
            <TextField fullWidth label="AWS Region" value={settings.awsRegion} onChange={handleChange('awsRegion')} />
          </Box>
        </Paper>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" gutterBottom>UI Preferences</Typography>
          <FormControlLabel
            control={<Switch checked={settings.autoRefresh} onChange={handleChange('autoRefresh')} />}
            label="Auto-refresh data"
          />
        </Paper>

        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" gutterBottom>System Information</Typography>
          <Box display="flex" gap={2}>
            <Chip label="v1.0.0" size="small" />
            <Chip label={import.meta.env.MODE} size="small" color={import.meta.env.MODE === 'production' ? 'success' : 'warning'} />
          </Box>
        </Paper>

        <Divider sx={{ my: 3 }} />
        <Box display="flex" justifyContent="flex-end">
          <Button variant="contained" onClick={handleSave}>Save Settings</Button>
        </Box>
      </Box>
    </Container>
  );
};
