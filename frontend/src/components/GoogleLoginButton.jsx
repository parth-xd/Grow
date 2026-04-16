import { useEffect, useState } from 'react';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

function GoogleLoginButton({ onSuccess, loading }) {
  const [error, setError] = useState(null);

  useEffect(() => {
    // DEBUG: Log environment variables
    console.log('=== OAUTH DEBUG ===');
    console.log('Client ID:', GOOGLE_CLIENT_ID);
    console.log('API URL:', API_URL);
    console.log('Client ID length:', GOOGLE_CLIENT_ID.length);
    console.log('Google API available:', !!window.google?.accounts?.id);
    
    // Wait for Google API to load
    const initGoogle = () => {
      if (!window.google?.accounts?.id) {
        console.log('Google API not ready, retrying...');
        setTimeout(initGoogle, 100);
        return;
      }

      try {
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: handleCredentialResponse,
          ux_mode: 'popup',
        });

        const button = document.getElementById('google-signin-button');
        if (button) {
          window.google.accounts.id.renderButton(button, {
            theme: 'outline',
            size: 'large',
            width: '100%',
            text: 'signin_with',
          });

          // Apply custom styling to match minimalist design
          setTimeout(() => {
            const btn = button.querySelector('button');
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
        }
      } catch (err) {
        console.error('Failed to initialize Google Sign-In:', err);
        setError('Failed to load Google Sign-In. Please refresh the page.');
      }
    };

    // Start initialization
    initGoogle();
  }, []);

  const handleCredentialResponse = async (response) => {
    try {
      // Send the ID token to backend for verification
      const result = await fetch(`${API_URL}/api/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token: response.credential }),
      });

      if (!result.ok) {
        const errorData = await result.json();
        console.error('Auth error:', errorData);
        setError(errorData.error || 'Authentication failed');
        return;
      }

      const data = await result.json();
      setError(null);
      onSuccess(data);
    } catch (err) {
      console.error('Login failed:', err);
      setError('Login failed. Please try again.');
    }
  };

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
        ⚠️ Google Client ID not configured
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">
        {error}
      </div>
    );
  }

  return <div id="google-signin-button" className="w-full"></div>;
}

export default GoogleLoginButton;
