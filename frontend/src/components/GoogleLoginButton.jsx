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
          // Create custom button instead of using Google's default
          const customBtn = document.createElement('button');
          customBtn.type = 'button';
          customBtn.className = 'w-full px-3 sm:px-4 py-2.5 sm:py-3 bg-white border-2 border-gray-200 rounded-lg sm:rounded-xl font-semibold text-sm sm:text-base text-gray-900 hover:border-gray-300 hover:bg-gray-50 transition-all duration-200 flex items-center justify-center gap-2 sm:gap-3 hover:shadow-md active:scale-95';
          
          customBtn.innerHTML = `
            <svg class="w-5 h-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            <span>Sign in with Google</span>
          `;
          
          customBtn.onclick = (e) => {
            e.preventDefault();
            setIsLoading(true);
            window.google.accounts.id.prompt((notification) => {
              if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
                // Fallback to normal flow
                window.google.accounts.id.renderButton(buttonContainer, {
                  theme: 'outline',
                  size: 'large',
                  width: '100%'
                });
              }
            });
          };
          
          buttonContainer.innerHTML = '';
          buttonContainer.appendChild(customBtn);
          
          setIsInitialized(true);
          console.log('✓ Google Sign-In initialized successfully');
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
      setError(null);
      setIsLoading(true);
      
      // Check if API URL is properly configured
      if (!API_URL || API_URL === 'http://localhost:5000') {
        console.warn('⚠️  Using default API URL. Set VITE_API_URL environment variable for production.');
      }
      
      const authUrl = `${API_URL}/api/auth/google`;
      console.log('Auth URL:', authUrl);
      
      const result = await fetch(authUrl, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ id_token: response.credential }),
      });

      console.log(`Backend response status: ${result.status}`);

      if (!result.ok) {
        let errorData;
        try {
          errorData = await result.json();
        } catch {
          errorData = { error: `HTTP ${result.status}`, detail: `Backend returned ${result.status}. Check API connection.` };
        }
        console.error('Auth error:', errorData);
        
        // Provide specific error messages
        let userMessage = errorData.error || 'Authentication failed';
        if (result.status === 404) {
          userMessage = 'Backend API not found. Please check server status.';
        } else if (result.status === 500) {
          userMessage = `Server error: ${errorData.detail || 'Internal server error'}`;
        } else if (result.status === 503) {
          userMessage = 'Backend service unavailable. Please try again in a moment.';
        }
        
        setError(userMessage);
        setIsLoading(false);
        return;
      }

      const data = await result.json();
      console.log('✓ Authentication successful');
      onSuccess(data);
    } catch (err) {
      console.error('Login request failed:', err);
      
      // Detect network errors
      if (err.message.includes('Failed to fetch')) {
        setError('Network error: Cannot reach backend server. Check your connection and API URL configuration.');
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
