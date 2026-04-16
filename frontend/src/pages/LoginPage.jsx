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
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 flex items-center justify-center px-4">
      {/* Decorative elements */}
      <div className="absolute top-0 left-0 w-96 h-96 bg-blue-50 rounded-full blur-3xl opacity-20 -z-10"></div>
      <div className="absolute bottom-0 right-0 w-96 h-96 bg-indigo-50 rounded-full blur-3xl opacity-20 -z-10"></div>

      <div className="max-w-md w-full">
        {/* Branding */}
        <div className="text-center mb-12 animate-fade-in">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-gray-900 to-gray-800 mb-6 shadow-lg">
            <span className="text-2xl font-bold text-white">G</span>
          </div>
          <h1 className="text-4xl font-bold text-gray-900 mb-2">Grow</h1>
          <p className="text-gray-500 text-base font-medium">Trade smarter, not harder</p>
        </div>

        {/* Login Card */}
        <div className="bg-white rounded-3xl p-8 shadow-xl border border-gray-100 backdrop-blur-sm">
          <h2 className="text-2xl font-bold text-gray-900 mb-1">Welcome Back</h2>
          <p className="text-gray-500 text-sm mb-8 font-medium">Sign in to your trading account</p>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-4 rounded-2xl mb-6 text-sm animate-pulse">
              <div className="flex justify-between items-start gap-3">
                <div className="flex items-start gap-2">
                  <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                  <span>{error}</span>
                </div>
                <button
                  onClick={clearError}
                  className="text-red-600 hover:text-red-800 font-bold ml-2"
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
          <div className="relative my-8">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200"></div>
            </div>
            <div className="relative flex justify-center">
              <span className="px-3 bg-white text-gray-400 text-xs font-semibold">OR</span>
            </div>
          </div>

          {/* Email signup info */}
          <p className="text-gray-500 text-sm text-center font-medium">
            Email authentication coming soon
          </p>
        </div>

        {/* Footer Links */}
        <div className="mt-8 text-center">
          <p className="text-gray-500 text-xs">
            By signing in, you agree to our{' '}
            <a href="#" className="text-gray-700 hover:text-gray-900 font-semibold transition-colors">
              Terms
            </a>
            {' '}and{' '}
            <a href="#" className="text-gray-700 hover:text-gray-900 font-semibold transition-colors">
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
