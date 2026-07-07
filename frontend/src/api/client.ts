/**
 * API client for AgentCore Debugger backend
 */
import axios, { AxiosInstance, AxiosResponse } from 'axios';

// API configuration
// - In development: Use VITE_API_URL or default to localhost:8000
// - In production: Use empty string (nginx proxies /api/* to backend)
const getApiBaseUrl = (): string => {
  // Check for explicit environment variable first
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  
  // In development mode, default to localhost:8000
  if (import.meta.env.DEV) {
    return 'http://localhost:8000';
  }
  
  // In production, use relative path (nginx proxies to backend)
  return '';
};

const API_BASE_URL = getApiBaseUrl();
const API_V1_PREFIX = '/api/v1';

// Create axios instance
// Timeout set to 5 minutes (300000ms) to handle long-running fix workflows
const apiClient: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}${API_V1_PREFIX}`,
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    return response;
  },
  (error) => {
    // Handle common errors
    if (error.response?.status === 401) {
      // Unauthorized - clear token and redirect to login
      localStorage.removeItem('auth_token');
    }
    return Promise.reject(error);
  }
);

export default apiClient;
export { apiClient, API_BASE_URL };
