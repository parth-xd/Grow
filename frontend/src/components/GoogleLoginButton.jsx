import { useEffect, useState } from 'react';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

function GoogleLoginButton({ onSuccess, loading }) {
  const [error, setError] = useState(null);
  const [isInitialized, setIsInitialized] = useState(false);

  useEffect(() => {
    console.log('=== Google Sign-In Initialization ===');
    console.log('Client ID present:', !!GOOGLE_CLIENT_ID);
    console.log('API URL:', API_URL);
    
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
          window.google.accounts.id.renderButton(buttonContainer, {
            theme: 'outline',
            size: 'large',
            width: '100%',
            text: 'signin_with',
          });

          // Apply custom styling
          setTimeout(() => {
            const btn = buttonContainer.querySelector('button');
            if (btn) {
              btn.style.background = '#ffffff';
              btn.style.color = '#1f2937';
              btn.style.borderRadius = '8px';
              btn.style.height = '48px';
              btn.style.fontWeight = '500';
              btn.style.fontSize = '14px';
              btn.style.width = '100%';
              btn.style.border = '1px solid #e5e7eb';
              btn.style.boxShadow = 'none';
              btn.style.transition = 'all 0.3s ease';
              
              btn.onmouseover = () => {
                btn.style.background = '#f9fafb';
                btn.style.borderColor = '#d1d5db';
                btn.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.1)';
              };
              btn.onmouseout = () => {
                btn.style.background = '#ffffff';
                btn.style.borderColor = '#e5e7eb';
                btn.style.boxShadow = 'none';
              };
            }
          }, 100);
          
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
      return;
    }

    try {
      console.log('🔐 Sending credential to backend...');
      setError(null);
      
      const result = await fetch(`${API_URL}/api/auth/google`, {
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
          errorData = { error: `HTTP ${result.status}` };
        }
        console.error('Auth error:', errorData);
        setError(errorData.error || errorData.detail || 'Authentication failed. Please try again.');
        return;
      }

      const data = await result.json();
      console.log('✓ Authentication successful');
      onSuccess(data);
    } catch (err) {
      console.error('Login request failed:', err);
      setError(err.message || 'Login failed. Check your connection and try again.');
    }
  };

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
        ⚠️ Configuration error: Google Client ID not set
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
        <button
          onClick={() => setError(null)}
          className="w-full px-4 py-2 text-sm text-blue-600 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition"
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
        <div className="mt-3 text-center text-gray-500 text-sm">
          <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-gray-900 mx-auto inline-block"></div>
          <p className="mt-2">Initializing...</p>
        </div>
      )}
    </div>
  );
}

export default GoogleLoginButton;
