import { useEffect } from 'react';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

function GoogleLoginButton({ onSuccess, loading }) {
  useEffect(() => {
    // DEBUG: Log environment variables
    console.log('=== OAUTH DEBUG ===');
    console.log('Client ID:', GOOGLE_CLIENT_ID);
    console.log('API URL:', API_URL);
    console.log('Client ID length:', GOOGLE_CLIENT_ID.length);
    console.log('Expected ID: 909946700089-5fr10qa7c51cl88ofmft1gp9f6eldsv1.apps.googleusercontent.com');
    console.log('Match:', GOOGLE_CLIENT_ID === '909946700089-5fr10qa7c51cl88ofmft1gp9f6eldsv1.apps.googleusercontent.com');
    
    // Initialize Google Sign-In button
    if (window.google?.accounts?.id) {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
        ux_mode: 'popup',
      });

      window.google.accounts.id.renderButton(
        document.getElementById('google-signin-button'),
        {
          theme: 'outline',
          size: 'large',
          width: '100%',
          text: 'signin_with',
        }
      );

      // Apply custom styling to match minimalist design
      setTimeout(() => {
        const button = document.getElementById('google-signin-button')?.querySelector('button');
        if (button) {
          button.style.background = '#ffffff';
          button.style.color = '#1f2937';
          button.style.borderRadius = '8px';
          button.style.height = '48px';
          button.style.fontWeight = '500';
          button.style.fontSize = '14px';
          button.style.width = '100%';
          button.style.border = '1px solid #e5e7eb';
          button.style.boxShadow = 'none';
          button.style.transition = 'all 0.3s ease';
          
          button.onmouseover = () => {
            button.style.background = '#f9fafb';
            button.style.borderColor = '#d1d5db';
            button.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.1)';
          };
          button.onmouseout = () => {
            button.style.background = '#ffffff';
            button.style.borderColor = '#e5e7eb';
            button.style.boxShadow = 'none';
          };
        }
      }, 500);
    }
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
        const error = await result.json();
        console.error('Auth error:', error);
        return;
      }

      const data = await result.json();
      onSuccess(data);
    } catch (error) {
      console.error('Login failed:', error);
    }
  };

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div className="bg-red-900/30 border border-red-800/50 text-red-300 px-4 py-3 rounded-lg text-sm">
        Google Client ID not configured
      </div>
    );
  }

  return <div id="google-signin-button" className="w-full"></div>;
}

export default GoogleLoginButton;
