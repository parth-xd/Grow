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
        toast.success('Welcome to Grow! 📈');
        navigate('/dashboard');
      } else {
        toast.error('Authentication failed');
      }
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-black via-gray-900 to-black flex items-center justify-center px-4 relative overflow-hidden">
      {/* Animated background elements */}
      <div className="absolute top-0 left-0 w-96 h-96 bg-yellow-400/5 rounded-full blur-3xl"></div>
      <div className="absolute bottom-0 right-0 w-96 h-96 bg-yellow-400/5 rounded-full blur-3xl"></div>

      <div className="max-w-md w-full relative z-10">
        {/* Branding */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-yellow-400 to-yellow-500 mb-6 shadow-lg shadow-yellow-400/50">
            <span className="text-2xl font-bold text-black">G</span>
          </div>
          <h1 className="text-4xl font-black text-white mb-2">Grow</h1>
          <p className="text-gray-400 text-base font-light tracking-wide">Trade smarter, not harder</p>
        </div>

        {/* Login Card */}
        <div className="backdrop-blur-md bg-gray-900/80 border border-gray-800 rounded-2xl p-8 shadow-2xl">
          <h2 className="text-xl font-semibold text-white mb-2">Get Started</h2>
          <p className="text-gray-400 text-sm mb-8">Sign in to access your trading dashboard</p>

          {error && (
            <div className="bg-red-900/30 border border-red-800/50 text-red-300 px-4 py-3 rounded-lg mb-6 text-sm">
              <div className="flex justify-between items-start">
                <span>{error}</span>
                <button
                  onClick={clearError}
                  className="text-red-300 hover:text-red-100 font-semibold ml-4"
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
              <div className="w-full border-t border-gray-800"></div>
            </div>
            <div className="relative flex justify-center">
              <span className="px-3 bg-gray-900/80 text-gray-500 text-xs tracking-widest uppercase">Or continue with</span>
            </div>
          </div>

          {/* Email signup info */}
          <p className="text-gray-500 text-xs text-center">
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
