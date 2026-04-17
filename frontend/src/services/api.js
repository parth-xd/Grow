import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json'
  },
  withCredentials: true // Allow cookies
});

// Decode JWT to check expiration
const decodeToken = (token) => {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64).split('').map((c) => {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
      }).join('')
    );
    return JSON.parse(jsonPayload);
  } catch (e) {
    return null;
  }
};

// Check if token is expired (with 5 min buffer)
const isTokenExpired = (token) => {
  const payload = decodeToken(token);
  if (!payload || !payload.exp) return true;
  
  const expirationTime = payload.exp * 1000; // Convert to milliseconds
  const currentTime = Date.now();
  const bufferTime = 5 * 60 * 1000; // 5 minutes
  
  return currentTime >= (expirationTime - bufferTime);
};

// Refresh token function
const refreshToken = async () => {
  try {
    console.log('🔄 Attempting to refresh access token...');
    const response = await axios.post(`${API_BASE_URL}/api/auth/refresh`, {}, {
      withCredentials: true
    });
    
    if (response.data.token) {
      localStorage.setItem('auth_token', response.data.token);
      console.log('✓ Access token refreshed');
      return response.data.token;
    }
  } catch (error) {
    console.error('Token refresh failed:', error.response?.status);
    // Refresh token invalid or expired - force logout
    localStorage.removeItem('auth_token');
    window.location.href = '/login';
  }
  return null;
};

let refreshPromise = null;

// Add token to all requests
api.interceptors.request.use(async (config) => {
  let token = localStorage.getItem('auth_token');
  
  if (!token) {
    console.warn('⚠️  No auth token found in localStorage for URL:', config.url);
  }
  
  // Check if token is expired and refresh if needed
  if (token && isTokenExpired(token)) {
    console.log('⚠️  Token expiring soon, refreshing...');
    
    // Prevent multiple refresh requests
    if (!refreshPromise) {
      refreshPromise = refreshToken().then(() => {
        refreshPromise = null;
      });
    }
    
    await refreshPromise;
    token = localStorage.getItem('auth_token');
  }
  
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
    console.debug('✓ Authorization header added to request:', config.url);
  } else {
    console.error('❌ No token available for authenticated request to:', config.url);
  }
  return config;
});

// Handle response errors
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    // If 401 and haven't tried refresh yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      
      console.log('⚠️  Received 401, attempting token refresh...');
      
      const newToken = await refreshToken();
      if (newToken) {
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      }
    }
    
    // Handle invalid_grant errors specifically
    if (error.response?.data?.error_description?.includes('invalid_grant')) {
      console.error('❌ Token revoked or session expired');
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
    }
    
    // Clear auth on 401 if refresh failed
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
    }
    
    return Promise.reject(error);
  }
);

export default api;
