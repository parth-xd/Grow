import { useState } from 'react';
import { GoogleLogin } from '@react-oauth/google';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

function GoogleLoginButton({ onSuccess, loading }) {
  const [localLoading, setLocalLoading] = useState(false);

  const handleSuccess = async (credentialResponse) => {
    if (!credentialResponse.credential) {
      console.error('No credential received');
      return;
    }

    setLocalLoading(true);
    try {
      // Decode the JWT to get the auth code (or send the credential directly)
      onSuccess(credentialResponse.credential);
    } finally {
      setLocalLoading(false);
    }
  };

  const handleError = (error) => {
    console.error('Login failed:', error);
  };

  if (!GOOGLE_CLIENT_ID) {
    return (
      <div className="bg-yellow-900 border border-yellow-700 text-yellow-100 px-4 py-3 rounded">
        Google Client ID not configured. Please set VITE_GOOGLE_CLIENT_ID in .env
      </div>
    );
  }

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <div className="w-full">
        <GoogleLogin
          onSuccess={handleSuccess}
          onError={handleError}
          theme="dark"
          size="large"
          width="100%"
        />
      </div>
    </GoogleOAuthProvider>
  );
}

export default GoogleLoginButton;
