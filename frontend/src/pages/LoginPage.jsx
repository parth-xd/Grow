import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import useAuthStore from '../store/authStore';
import GoogleLoginButton from '../components/GoogleLoginButton';

function LoginPage() {
  const navigate = useNavigate();
  const { handleGoogleAuth, loading, error, clearError } = useAuthStore();

  const handleGoogleSuccess = async (response) => {
    if (response.token) {
      const success = await handleGoogleAuth(response);
      if (success) {
        // Check if user has API credentials
        try {
          const credResponse = await fetch(`${import.meta.env.VITE_API_URL}/api/credentials/status`, {
            headers: {
              'Authorization': `Bearer ${response.token}`
            }
          });
          
          if (credResponse.ok) {
            const credData = await credResponse.json();
            if (credData.has_credentials) {
              // User has credentials, go to dashboard
              toast.success('Welcome to Grow! 📈');
              navigate('/dashboard');
            } else {
              // No credentials, go to settings to add them
              toast.success('Welcome! Please add your Groww credentials');
              navigate('/settings');
            }
          } else {
            // If we can't check, just go to dashboard
            toast.success('Welcome to Grow! 📈');
            navigate('/dashboard');
          }
        } catch (err) {
          console.error('Credentials check failed:', err);
          toast.success('Welcome to Grow! 📈');
          navigate('/dashboard');
        }
      } else {
        toast.error('Authentication failed');
      }
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        {/* Branding */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-gray-900 mb-6">
            <span className="text-xl font-bold text-white">G</span>
          </div>
          <h1 className="text-3xl font-semibold text-gray-900 mb-2">Grow</h1>
          <p className="text-gray-600 text-sm">Trade smarter, not harder</p>
        </div>

        {/* Login Card */}
        <div className="bg-white rounded-2xl p-8 border border-gray-200 shadow-sm">
          <h2 className="text-xl font-semibold text-gray-900 mb-2">Welcome Back</h2>
          <p className="text-gray-600 text-sm mb-8">Sign in to your account</p>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6 text-sm">
              <div className="flex justify-between items-start">
                <span>{error}</span>
                <button
                  onClick={clearError}
                  className="text-red-600 hover:text-red-800 font-semibold ml-4"
                >
                  ×
                </button>
              </div>
            </div>
          )}

          {/* Google Login Button */}
          <GoogleLoginButton
            onSuccess={handleGoogleSuccess}
            loading={loading}
          />

          {/* Divider */}
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200"></div>
            </div>
            <div className="relative flex justify-center">
              <span className="px-3 bg-white text-gray-500 text-xs">Or</span>
            </div>
          </div>

          {/* Email signup info */}
          <p className="text-gray-600 text-xs text-center">
            Email authentication coming soon
          </p>
        </div>

        {/* Footer Links */}
        <div className="mt-8 text-center">
          <p className="text-gray-500 text-xs">
            By signing in, you agree to our{' '}
            <a href="#" className="text-yellow-400 hover:text-yellow-300 transition-colors">
              Terms
            </a>
            {' '}and{' '}
            <a href="#" className="text-yellow-400 hover:text-yellow-300 transition-colors">
              Privacy Policy
            </a>
          </p>
        </div>

        {/* Stats/Features */}
        <div className="mt-12 grid grid-cols-3 gap-3">
          <StatCard number="10K+" label="Traders" />
          <StatCard number="₹50Cr" label="Traded" />
          <StatCard number="24/7" label="Support" />
        </div>
      </div>
    </div>
  );
}

function StatCard({ number, label }) {
  return (
    <div className="text-center">
      <div className="text-lg font-bold text-yellow-400 mb-1">{number}</div>
      <p className="text-gray-500 text-xs">{label}</p>
    </div>
  );
}

export default LoginPage;
