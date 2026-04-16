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
          theme: 'filled_black',
          size: 'large',
          width: '100%',
          text: 'signin_with',
        }
      );

      // Apply custom styling to match black & yellow theme
      setTimeout(() => {
        const button = document.getElementById('google-signin-button')?.querySelector('button');
        if (button) {
          button.style.background = '#FBBF24';
          button.style.color = '#000000';
          button.style.borderRadius = '10px';
          button.style.height = '50px';
          button.style.fontWeight = '600';
          button.style.fontSize = '15px';
          button.style.width = '100%';
          button.style.border = 'none';
          button.style.boxShadow = '0 4px 15px rgba(251, 191, 36, 0.3)';
          button.style.transition = 'all 0.3s ease';
          
          button.onmouseover = () => {
            button.style.background = '#FCD34D';
            button.style.boxShadow = '0 6px 20px rgba(251, 191, 36, 0.4)';
            button.style.transform = 'translateY(-2px)';
          };
          button.onmouseout = () => {
            button.style.background = '#FBBF24';
            button.style.boxShadow = '0 4px 15px rgba(251, 191, 36, 0.3)';
            button.style.transform = 'translateY(0)';
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
