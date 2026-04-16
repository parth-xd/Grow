import { useEffect } from 'react';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

function GoogleLoginButton({ onSuccess, loading }) {
  useEffect(() => {
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
      <div className="bg-yellow-900 border border-yellow-700 text-yellow-100 px-4 py-3 rounded">
        Google Client ID not configured. Please set VITE_GOOGLE_CLIENT_ID in .env
      </div>
    );
  }

  return <div id="google-signin-button" className="w-full"></div>;
}

export default GoogleLoginButton;
