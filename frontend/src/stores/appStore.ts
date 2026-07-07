/**
 * Global application state management using Zustand
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { Agent, AgentFilters } from '../types/agent';

interface TimeRange {
  start: Date | null;
  end: Date | null;
}

interface AppState {
  // Selected agent
  selectedAgent: Agent | null;
  setSelectedAgent: (agent: Agent | null) => void;

  // Time range for metrics and logs
  timeRange: TimeRange;
  setTimeRange: (range: TimeRange) => void;

  // Agent filters
  agentFilters: AgentFilters;
  setAgentFilters: (filters: AgentFilters) => void;

  // UI state
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;

  // Auto-refresh
  autoRefresh: boolean;
  setAutoRefresh: (enabled: boolean) => void;

  // Loading states
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;

  // Last visited route (for restoration after refresh)
  lastRoute: string;
  setLastRoute: (route: string) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // Selected agent
      selectedAgent: null,
      setSelectedAgent: (agent) => set({ selectedAgent: agent }),

      // Time range (default: last 24 hours)
      timeRange: {
        start: new Date(Date.now() - 24 * 60 * 60 * 1000),
        end: new Date(),
      },
      setTimeRange: (range) => set({ timeRange: range }),

      // Agent filters
      agentFilters: {
        limit: 100,
        offset: 0,
      },
      setAgentFilters: (filters) => set({ agentFilters: filters }),

      // UI state
      sidebarOpen: true,
      setSidebarOpen: (open) => set({ sidebarOpen: open }),

      // Auto-refresh
      autoRefresh: false,
      setAutoRefresh: (enabled) => set({ autoRefresh: enabled }),

      // Loading states
      isLoading: false,
      setIsLoading: (loading) => set({ isLoading: loading }),

      // Last visited route
      lastRoute: '/',
      setLastRoute: (route) => set({ lastRoute: route }),
    }),
    {
      name: 'agentcore-app',
      partialize: (state) => ({
        // Only persist these fields
        sidebarOpen: state.sidebarOpen,
        lastRoute: state.lastRoute,
      }),
    }
  )
);
