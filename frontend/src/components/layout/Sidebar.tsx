/**
 * Sidebar navigation component with role-based visibility
 */
import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Box,
  Divider,
} from '@mui/material';
import {
  Dashboard,
  SmartToy,
  Error,
  Settings,
  BugReport,
} from '@mui/icons-material';
import { useAuthStore, UserRole } from '../../stores/authStore';

const DRAWER_WIDTH = 240;

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
  minRole?: UserRole; // minimum role required to see this item
}

const navItems: NavItem[] = [
  { path: '/', label: 'Dashboard', icon: <Dashboard /> },
  { path: '/agents', label: 'Agents', icon: <SmartToy /> },
  { path: '/errors', label: 'Error Analysis', icon: <Error /> },
  { path: '/test-errors', label: 'Test Errors', icon: <BugReport /> },
];

const bottomNavItems: NavItem[] = [
  { path: '/settings', label: 'Settings', icon: <Settings />, minRole: 'admin' },
];

interface SidebarProps {
  open: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({ open }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { hasRole } = useAuthStore();

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  const visibleItems = (items: NavItem[]) =>
    items.filter((item) => !item.minRole || hasRole(item.minRole));

  return (
    <Drawer
      variant="persistent"
      anchor="left"
      open={open}
      sx={{
        width: open ? DRAWER_WIDTH : 0,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          boxSizing: 'border-box',
        },
      }}
    >
      <Toolbar>
        <Box display="flex" alignItems="center" gap={1}>
          <SmartToy color="primary" />
          <Typography variant="h6" noWrap>
            AgentCore
          </Typography>
        </Box>
      </Toolbar>
      <Divider />

      <List sx={{ flex: 1 }}>
        {visibleItems(navItems).map((item) => (
          <ListItem key={item.path} disablePadding>
            <ListItemButton
              selected={isActive(item.path)}
              onClick={() => navigate(item.path)}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>

      <Divider />
      <List>
        {visibleItems(bottomNavItems).map((item) => (
          <ListItem key={item.path} disablePadding>
            <ListItemButton
              selected={isActive(item.path)}
              onClick={() => navigate(item.path)}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </Drawer>
  );
};
