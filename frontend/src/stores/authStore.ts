/**
 * Authentication state management using Zustand.
 *
 * Handles Cognito Hosted UI OAuth2 PKCE flow:
 *   1. User clicks "Sign In" → redirect to Cognito Hosted UI
 *   2. Cognito redirects back with ?code=xxx
 *   3. We exchange the code for tokens
 *   4. Tokens are stored in memory (access) and localStorage (refresh)
 *
 * When AUTH_ENABLED=false on the backend, the store stays in
 * "authenticated" mode with a dummy dev user so the rest of the
 * app works unchanged.
 */
import { create } from 'zustand';
import apiClient, { API_BASE_URL } from '../api/client';

export type UserRole = 'viewer' | 'operator' | 'admin';

interface AuthUser {
  sub: string;
  email: string;
  username: string;
  roles: UserRole[];
}

interface AuthConfig {
  auth_enabled: boolean;
  cognito_user_pool_id: string;
  cognito_app_client_id: string;
  cognito_region: string;
  cognito_domain: string;
}

interface AuthState {
  // State
  user: AuthUser | null;
  token: string | null;
  authConfig: AuthConfig | null;
  isLoading: boolean;
  isInitialized: boolean;
  error: string | null;

  // Actions
  initialize: () => Promise<void>;
  login: () => void;
  logout: () => void;
  handleCallback: (code: string) => Promise<void>;
  hasRole: (role: UserRole) => boolean;
  clearError: () => void;
}

// Role hierarchy check
const ROLE_HIERARCHY: Record<UserRole, UserRole[]> = {
  viewer: ['viewer'],
  operator: ['viewer', 'operator'],
  admin: ['viewer', 'operator', 'admin'],
};

function getCognitoDomain(): string {
  // The Cognito hosted-UI domain is injected at BUILD time (Vite inlines
  // import.meta.env.* as a string literal), not read from a runtime HTTP
  // response — so it is a trusted constant, never user/network-controlled.
  // The pipeline sets VITE_COGNITO_DOMAIN from the stack's Cognito domain output.
  const domain = import.meta.env.VITE_COGNITO_DOMAIN as string | undefined;
  if (!domain) {
    throw new Error('VITE_COGNITO_DOMAIN is not configured for this build');
  }
  // Validate it is a well-formed HTTPS Amazon Cognito hosted-UI domain.
  const u = new URL(domain);
  if (u.protocol !== 'https:' || !/^[a-z0-9-]+\.auth\.[a-z0-9-]+\.amazoncognito\.com$/.test(u.host)) {
    throw new Error('Invalid VITE_COGNITO_DOMAIN');
  }
  return `https://${u.host}`;
}

function getRedirectUri(): string {
  return `${window.location.origin}/auth/callback`;
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  user: null,
  token: null,
  authConfig: null,
  isLoading: true,
  isInitialized: false,
  error: null,

  initialize: async () => {
    try {
      // Fetch auth config from backend via the app API client (axios).
      const resp = await apiClient.get('/auth/config', { baseURL: API_BASE_URL });
      const config: AuthConfig = resp.data;

      if (!config.auth_enabled) {
        // Dev mode — no auth required
        set({
          authConfig: config,
          user: { sub: 'dev', email: 'dev@localhost', username: 'dev-user', roles: ['admin'] },
          token: null,
          isLoading: false,
          isInitialized: true,
        });
        return;
      }

      set({ authConfig: config });

      // Check for existing token in localStorage
      const savedToken = localStorage.getItem('auth_token');
      if (savedToken) {
        try {
          // Validate the saved token via the app API client (axios). The
          // client injects the bearer token and uses the configured base URL,
          // so no raw fetch to a dynamic URL is needed here.
          await apiClient.get('/health/system');

          // Token is valid — parse the user from its payload.
          const payload = JSON.parse(atob(savedToken.split('.')[1]));
          const groups: string[] = payload['cognito:groups'] || [];
          const roles: UserRole[] = groups
            .map((g: string) => g.toLowerCase())
            .filter((g: string): g is UserRole => ['viewer', 'operator', 'admin'].includes(g));

          set({
            user: {
              sub: payload.sub,
              email: payload.email || '',
              username: payload['cognito:username'] || payload.sub,
              roles: roles.length ? roles : ['viewer'],
            },
            token: savedToken,
            isLoading: false,
            isInitialized: true,
          });
          return;
        } catch {
          localStorage.removeItem('auth_token');
        }
      }

      set({ isLoading: false, isInitialized: true });
    } catch (e) {
      set({
        error: 'Failed to load auth configuration',
        isLoading: false,
        isInitialized: true,
      });
    }
  },

  login: () => {
    const { authConfig } = get();
    if (!authConfig?.auth_enabled) return;

    const domain = getCognitoDomain();
    const params = new URLSearchParams({
      client_id: authConfig.cognito_app_client_id,
      response_type: 'code',
      scope: 'openid email profile',
      redirect_uri: getRedirectUri(),
    });
    window.location.href = `${domain}/login?${params}`;
  },

  handleCallback: async (code: string) => {
    const { authConfig } = get();
    if (!authConfig) throw new Error('Auth not initialized');

    set({ isLoading: true, error: null });

    try {
      // Exchange the authorization code for tokens via our backend
      // (POST /auth/token). The browser never makes the cross-origin request
      // to Cognito itself — the backend holds the hosted-UI domain in config
      // and performs the exchange. We call it through the axios client with a
      // base URL override so it hits the root /auth/token route.
      console.log('[Auth] Exchanging code for tokens via backend /auth/token');

      const resp = await apiClient.post(
        '/auth/token',
        { code, redirect_uri: getRedirectUri() },
        { baseURL: API_BASE_URL }
      );

      const idToken = resp.data.id_token;
      if (!idToken) {
        throw new Error('Token exchange did not return an id_token');
      }

      // Parse user info from ID token
      const payload = JSON.parse(atob(idToken.split('.')[1]));
      const groups: string[] = payload['cognito:groups'] || [];
      const roles: UserRole[] = groups
        .map((g: string) => g.toLowerCase())
        .filter((g: string): g is UserRole => ['viewer', 'operator', 'admin'].includes(g));

      localStorage.setItem('auth_token', idToken);

      set({
        user: {
          sub: payload.sub,
          email: payload.email || '',
          username: payload['cognito:username'] || payload.sub,
          roles: roles.length ? roles : ['viewer'],
        },
        token: idToken,
        isLoading: false,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Authentication failed';
      console.error('[Auth] handleCallback error:', msg);
      set({ error: msg, isLoading: false });
      throw e;
    }
  },

  logout: () => {
    const { authConfig } = get();
    localStorage.removeItem('auth_token');
    set({ user: null, token: null });

    if (authConfig?.auth_enabled) {
      const domain = getCognitoDomain();
      const params = new URLSearchParams({
        client_id: authConfig.cognito_app_client_id,
        logout_uri: window.location.origin,
      });
      window.location.href = `${domain}/logout?${params}`;
    }
  },

  hasRole: (role: UserRole) => {
    const { user } = get();
    if (!user) return false;
    return user.roles.some((r) => ROLE_HIERARCHY[r]?.includes(role));
  },

  clearError: () => set({ error: null }),
}));
