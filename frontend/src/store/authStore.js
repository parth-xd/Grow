import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import api from '../services/api';

const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      loading: false,
      error: null,

      // Check if user is authenticated
      checkAuth: async () => {
        const token = localStorage.getItem('auth_token');
        if (!token) {
          set({ isAuthenticated: false, user: null });
          return;
        }

        try {
          // Add a 5 second timeout to prevent hanging indefinitely
          const timeoutPromise = new Promise((_, reject) =>
            setTimeout(() => reject(new Error('Auth check timeout')), 5000)
          );

          const response = await Promise.race([
            api.get('/api/auth/verify'),
            timeoutPromise
          ]);

          set({
            user: response.data.user,
            token,
            isAuthenticated: true,
            error: null
          });
        } catch (error) {
          // If auth check fails or times out, clear token and let user login again
          console.error('Auth check failed:', error.message);
          localStorage.removeItem('auth_token');
          set({
            isAuthenticated: false,
            user: null,
            token: null,
            error: error.message || 'Token expired'
          });
        }
      },

      // Handle Google OAuth callback
      handleGoogleAuth: async (response) => {
        set({ loading: true, error: null });
        try {
          // response already has { token, user } from backend
          const { token, user } = response;

          // Save token
          localStorage.setItem('auth_token', token);

          set({
            user,
            token,
            isAuthenticated: true,
            loading: false,
            error: null
          });

          return true;
        } catch (error) {
          set({
            loading: false,
            error: error.response?.data?.error || 'Authentication failed'
          });
          return false;
        }
      },

      // Login with email/password (if implemented)
      login: async (email, password) => {
        set({ loading: true, error: null });
        try {
          const response = await api.post('/api/auth/login', {
            email,
            password
          });

          const { token, user } = response.data;
          localStorage.setItem('auth_token', token);

          set({
            user,
            token,
            isAuthenticated: true,
            loading: false
          });

          return true;
        } catch (error) {
          set({
            loading: false,
            error: error.response?.data?.error || 'Login failed'
          });
          return false;
        }
      },

      // Logout
      logout: async () => {
        try {
          await api.post('/api/auth/logout');
        } catch (error) {
          console.error('Logout error:', error);
        }

        localStorage.removeItem('auth_token');
        set({
          user: null,
          token: null,
          isAuthenticated: false,
          error: null
        });
      },

      // Update user profile
      updateProfile: async (updates) => {
        set({ loading: true, error: null });
        try {
          const response = await api.put('/api/users/profile', updates);

          set({
            user: response.data.user,
            loading: false
          });

          return true;
        } catch (error) {
          set({
            loading: false,
            error: error.response?.data?.error || 'Update failed'
          });
          return false;
        }
      },

      // Clear error
      clearError: () => set({ error: null })
    }),
    {
      name: 'auth-store',
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        isAuthenticated: state.isAuthenticated
      })
    }
  )
);

export default useAuthStore;
