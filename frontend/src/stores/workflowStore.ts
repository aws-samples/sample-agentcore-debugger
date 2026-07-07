/**
 * Workflow State Store
 * Manages the connected workflow state across pages.
 *
 * FLOW:
 * 1. Select an agent → enables error analysis
 * 2. Review errors → see error patterns from CloudWatch
 * 3. Apply fixes → AI generates code fixes (stored with a working directory)
 * 4. Deploy & test → the /test page deploys the fix as a draft, tests it,
 *    and (admin) promotes it to production
 *
 * The fix → /test handoff relies on workingDirectory / fixAllWorkingDirectory
 * via getTestWorkingDirectory().
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface FixedPattern {
  patternId: string;
  errorMessage: string;
  fixedFiles: Record<string, string>;
  codeSummary: string;
  timestamp: string;
  // Classification data for restoring UI state when returning to page
  classification?: {
    type: string;
    confidence: number;
    reasoning: string;
  };
  // Full fix result for restoring UI state when returning to page
  fixResult?: {
    status: string;
    workflow_type?: string;
    fixed_files?: Record<string, string>;
    original_files?: Record<string, string>;  // Original file contents for diff
    working_directory?: string;
    code_agent_summary?: string;
    library_agent_output?: string;
    message?: string;
  };
}

export interface InProgressFix {
  patternId: string;
  agentId: string;
  startedAt: string;
  errorMessage: string;
  isFixAll?: boolean;  // True if this is part of a "Fix All" operation
  fixAllTotal?: number;  // Total patterns in Fix All
  fixAllCompleted?: number;  // Completed patterns in Fix All
  fixAllSessionId?: string;  // Unique session ID for Fix All workspace isolation
}

export interface WorkflowState {
  // Current agent context - the foundation of the workflow
  selectedAgentId: string | null;
  selectedAgentName: string | null;
  
  // In-progress fix tracking (survives page refresh)
  inProgressFix: InProgressFix | null;
  
  // Track if last fix was "Fix All" (to show global Next Steps instead of per-pattern)
  wasFixAllOperation: boolean;
  
  // Fix workflow results - produced by the error analysis / fix pages
  workingDirectory: string | null;
  // Separate tracking for Fix All shared workspace. When Fix All is used, this
  // stores the shared workspace that all patterns use; the /test page uses this
  // when wasFixAllOperation is true.
  fixAllWorkingDirectory: string | null;
  fixedPatterns: FixedPattern[];
  lastFixTimestamp: string | null;
  
  // Current step in fix workflow
  fixWorkflowStep: 'select' | 'review' | 'fix' | 'complete';
  
  // Actions
  setSelectedAgent: (agentId: string, agentName: string) => void;
  setWorkingDirectory: (dir: string) => void;
  setFixAllWorkingDirectory: (dir: string | null) => void;
  addFixedPattern: (pattern: FixedPattern) => void;
  clearFixedPatterns: () => void;
  setFixWorkflowStep: (step: WorkflowState['fixWorkflowStep']) => void;
  resetWorkflow: () => void;
  
  // In-progress fix tracking
  setInProgressFix: (fix: InProgressFix | null) => void;
  clearInProgressFix: () => void;
  
  // Fix All operation tracking
  setWasFixAllOperation: (value: boolean) => void;
  
  // Get the appropriate working directory for the /test (deploy & test) page.
  // Returns fixAllWorkingDirectory if wasFixAllOperation is true, otherwise workingDirectory.
  getTestWorkingDirectory: () => string | null;
  
  // Computed helpers
  hasFixedCode: () => boolean;
  canTest: () => boolean;
}

const initialState = {
  selectedAgentId: null,
  selectedAgentName: null,
  inProgressFix: null,
  wasFixAllOperation: false,
  workingDirectory: null,
  fixAllWorkingDirectory: null,
  fixedPatterns: [],
  lastFixTimestamp: null,
  fixWorkflowStep: 'select' as const,
};

export const useWorkflowStore = create<WorkflowState>()(
  persist(
    (set, get) => ({
      ...initialState,
      
      setSelectedAgent: (agentId: string, agentName: string) => {
        const currentAgentId = get().selectedAgentId;
        // Only reset data if agent actually changes
        if (currentAgentId === agentId) {
          set({ selectedAgentName: agentName });
          return;
        }
        // Different agent - reset all downstream state
        set({
          selectedAgentId: agentId,
          selectedAgentName: agentName,
          workingDirectory: null,
          fixAllWorkingDirectory: null,
          fixedPatterns: [],
          lastFixTimestamp: null,
          fixWorkflowStep: 'review',
        });
      },
      
      setWorkingDirectory: (dir: string) => set({ workingDirectory: dir }),
      
      setFixAllWorkingDirectory: (dir: string | null) => set({ fixAllWorkingDirectory: dir }),
      
      addFixedPattern: (pattern: FixedPattern) => set((state: WorkflowState) => ({
        fixedPatterns: [...state.fixedPatterns, pattern],
        lastFixTimestamp: new Date().toISOString(),
        fixWorkflowStep: 'fix',
      })),
      
      clearFixedPatterns: () => set({
        fixedPatterns: [],
        lastFixTimestamp: null,
        fixWorkflowStep: 'review',
      }),
      
      setFixWorkflowStep: (step: WorkflowState['fixWorkflowStep']) => set({ fixWorkflowStep: step }),
      
      resetWorkflow: () => set(initialState),
      
      setInProgressFix: (fix: InProgressFix | null) => set({ inProgressFix: fix }),
      
      clearInProgressFix: () => set({ inProgressFix: null }),
      
      setWasFixAllOperation: (value: boolean) => set({ wasFixAllOperation: value }),
      
      getTestWorkingDirectory: () => {
        const state = get();
        if (state.wasFixAllOperation && state.fixAllWorkingDirectory) {
          return state.fixAllWorkingDirectory;
        }
        return state.workingDirectory;
      },
      
      hasFixedCode: () => {
        const state = get();
        return state.fixedPatterns.length > 0 && !!state.workingDirectory;
      },
      
      canTest: () => {
        const state = get();
        return !!state.workingDirectory && state.fixedPatterns.length > 0;
      },
    }),
    {
      name: 'agentcore-workflow',
    }
  )
);
