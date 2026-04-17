import { useEffect, useState } from 'react';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

function GoogleLoginButton({ onSuccess, loading }) {
  const [error, setError] = useState(null);
  const [isInitialized, setIsInitialized] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    console.log('=== Google Sign-In Initialization ===');
    console.log('Client ID present:', !!GOOGLE_CLIENT_ID);
    
    // Suppress COOP warnings in console (they're from browser, not actually breaking)
    if (window.console) {
      const originalError = window.console.error;
      window.console.error = function(...args) {
        if (args[0]?.includes?.('Cross-Origin-Opener-Policy')) {
          console.log('ℹ️  COOP policy notice (non-critical):', args[0]);
          return;
        }
        originalError.apply(window.console, args);
      };
    }
    
    // Wait for Google API to load
    const initGoogle = () => {
      if (!window.google?.accounts?.id) {
        console.log('Google API not ready, retrying...');
        setTimeout(initGoogle, 100);
        return;
      }

      try {
        console.log('Initializing Google Sign-In...');
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: handleCredentialResponse,
          ux_mode: 'popup',
          auto_select: false,
        });

        const buttonContainer = document.getElementById('google-signin-button');
        if (buttonContainer) {
          // Use Google's official button via renderButton - handles credential flow properly
          // Note: renderButton doesn't accept 'width' parameter, CSS handles sizing
          window.google.accounts.id.renderButton(buttonContainer, {
            theme: 'outline',
            size: 'large',
            type: 'standard',
            text: 'signin_with'
            // Don't set width here - let CSS handle it
          });
          
          setIsInitialized(true);
          console.log('✓ Google Sign-In button rendered successfully');
        }
      } catch (err) {
        console.error('Failed to initialize Google Sign-In:', err);
        setError('Failed to load Google Sign-In. Please refresh the page.');
      }
    };

    initGoogle();
  }, []);

  const handleCredentialResponse = async (response) => {
    if (!response.credential) {
      console.error('No credential in response');
      setError('Sign-in failed: No credential received');
      setIsLoading(false);
      return;
    }

    try {
      console.log('🔐 Sending credential to backend...');
      console.log('API URL:', API_URL);
      console.log('Token length:', response.credential.length);
      setError(null);
      setIsLoading(true);
      
      // Check if API URL is properly configured
      if (!API_URL || API_URL === 'http://localhost:5000') {
        console.warn('⚠️  Using default API URL. Set VITE_API_URL environment variable for production.');
      }
      
      const authUrl = `${API_URL}/api/auth/google`;
      console.log('Auth URL:', authUrl);
      
      let result;
      try {
        console.log('📤 Sending POST request...');
        result = await fetch(authUrl, {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          },
          credentials: 'include', // Include credentials for FedCM
          body: JSON.stringify({ id_token: response.credential }),
        });

        console.log(`📨 Backend response status: ${result.status} ${result.statusText}`);
      } catch (fetchErr) {
        console.error('❌ Fetch failed:', fetchErr.message);
        setError(`Network error: ${fetchErr.message}`);
        setIsLoading(false);
        return;
      }

      if (!result.ok) {
        let errorData;
        try {
          const text = await result.text();
          console.log('Response body:', text);
          errorData = text ? JSON.parse(text) : { error: `HTTP ${result.status}` };
        } catch (parseErr) {
          console.error('Failed to parse error response:', parseErr);
          errorData = { error: `HTTP ${result.status}`, detail: 'Backend error' };
        }
        console.error('❌ Auth error:', result.status, errorData);
        
        // Provide specific error messages
        let userMessage = errorData.error || 'Authentication failed';
        if (result.status === 404) {
          userMessage = 'Backend API not found. Is the server running?';
        } else if (result.status === 401) {
          userMessage = `Auth error: ${errorData.detail || 'Invalid credentials'}`;
        } else if (result.status === 500) {
          userMessage = `Server error: ${errorData.detail || 'Internal server error'}`;
        } else if (result.status === 503) {
          userMessage = 'Backend service unavailable. Please try again in a moment.';
        } else if (result.status === 0) {
          userMessage = 'Network error: Cannot reach backend. Check API_URL configuration.';
        }
        
        setError(userMessage);
        setIsLoading(false);
        return;
      }

      let data;
      try {
        data = await result.json();
        console.log('✅ Authentication successful');
        console.log('User:', data.user);
        
        // Warn if email not verified
        if (data.user && !data.user.email_verified) {
          console.warn('⚠️  Email not verified - user may have limited access');
        }
        
        onSuccess(data);
      } catch (parseErr) {
        console.error('❌ Failed to parse success response:', parseErr);
        setError('Invalid server response. Check backend logs.');
        setIsLoading(false);
      }
    } catch (err) {
      console.error('❌ Sign-in error:', err);
      
      // Detect specific errors
      if (err.message.includes('Failed to fetch')) {
        setError('Network error: Cannot reach backend server. Check your connection and VITE_API_URL.');
      } else if (err.message.includes('CORS')) {
        setError('CORS error: Backend blocked the request. Check server CORS settings.');
      } else {
        setError(err.message || 'Login failed. Check your connection and try again.');
      }
      setIsLoading(false);
    }
  };

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-2xl text-sm flex items-start gap-2">
        <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
        <span>Configuration error: Google Client ID not set</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-4 rounded-2xl text-sm flex items-start gap-3">
          <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <span>{error}</span>
        </div>
        <button
          onClick={() => setError(null)}
          className="w-full px-4 py-3 text-sm font-semibold text-blue-600 bg-blue-50 border border-blue-200 rounded-xl hover:bg-blue-100 transition-all duration-200 active:scale-95"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div>
      <div id="google-signin-button" className="w-full"></div>
      {!isInitialized && (
        <div className="mt-4 text-center">
          <div className="animate-spin rounded-full h-5 w-5 border-2 border-gray-300 border-t-gray-900 mx-auto mb-2"></div>
          <p className="text-gray-500 text-sm font-medium">Loading...</p>
        </div>
      )}
      {isLoading && (
        <div className="mt-4 text-center">
          <div className="animate-spin rounded-full h-5 w-5 border-2 border-blue-300 border-t-blue-600 mx-auto mb-2"></div>
          <p className="text-blue-600 text-sm font-medium">Signing you in...</p>
        </div>
      )}
    </div>
  );
}

export default GoogleLoginButton;
