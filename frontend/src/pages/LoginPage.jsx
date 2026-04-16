import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import useAuthStore from '../store/authStore';
import GoogleLoginButton from '../components/GoogleLoginButton';

function LoginPage() {
  const navigate = useNavigate();
  const { handleGoogleAuth, loading, error, clearError } = useAuthStore();

  const handleGoogleSuccess = async (response) => {
    // response should contain { token, user }
    if (response.token) {
      // Store token in auth store
      const success = await handleGoogleAuth(response);
      if (success) {
        toast.success('Login successful!');
        navigate('/dashboard');
      } else {
        toast.error('Login failed. Please try again.');
      }
    }
  };

  return (
    <div className="min-h-screen bg-white flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        {/* Logo */}
        <div className="text-center mb-10">
          <h1 className="text-5xl font-bold text-gray-900 mb-2">Groww AI</h1>
          <p className="text-gray-600 text-lg">Intelligent Trading Platform</p>
        </div>

        {/* Login Card */}
        <div className="card p-8">
          <h2 className="text-2xl font-semibold text-gray-900 mb-8">Welcome back</h2>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6 text-sm">
              <div className="flex justify-between items-start">
                <span>{error}</span>
                <button
                  onClick={clearError}
                  className="text-red-700 hover:text-red-900 font-semibold"
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

          {/* Or Divider */}
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-white text-gray-600 font-medium">Or</span>
            </div>
          </div>

          {/* Email/Password Form (Optional) */}
          <p className="text-gray-500 text-sm text-center">
            Email/password authentication coming soon
          </p>
        </div>

        {/* Footer */}
        <div className="mt-8 text-center text-gray-600 text-sm">
          <p>
            By signing in, you agree to our{' '}
            <a href="#" className="text-blue-600 hover:text-blue-700 font-medium">
              Terms of Service
            </a>{' '}
            and{' '}
            <a href="#" className="text-blue-600 hover:text-blue-700 font-medium">
              Privacy Policy
            </a>
          </p>
        </div>

        {/* Features Preview */}
        <div className="mt-12 grid grid-cols-3 gap-4">
          <FeatureItem number="01" label="ML Models" description="Intelligent algorithms" />
          <FeatureItem number="02" label="Analytics" description="Deep insights" />
          <FeatureItem number="03" label="Real-time" description="Live updates" />
        </div>
      </div>
    </div>
  );
}

function FeatureItem({ number, label, description }) {
  return (
    <div className="card p-4 text-center hover:shadow-md transition-shadow">
      <div className="text-2xl font-bold text-blue-500 mb-2">{number}</div>
      <p className="text-gray-900 font-semibold text-sm">{label}</p>
      <p className="text-gray-500 text-xs mt-1">{description}</p>
    </div>
  );
}

export default LoginPage;
