import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';

function SettingsPage() {
  const navigate = useNavigate();
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [loading, setLoading] = useState(false);
  const [hasCredentials, setHasCredentials] = useState(false);
  const [checkingCredentials, setCheckingCredentials] = useState(true);

  useEffect(() => {
    checkCredentials();
  }, []);

  const checkCredentials = async () => {
    try {
      const response = await api.get('/api/credentials/status');
      setHasCredentials(response.data.has_credentials);
    } catch (error) {
      console.error('Failed to check credentials:', error);
    } finally {
      setCheckingCredentials(false);
    }
  };

  const handleSaveCredentials = async () => {
    if (!apiKey || !apiSecret) {
      toast.error('Please fill all fields');
      return;
    }

    setLoading(true);
    try {
      await api.post('/api/credentials/save', {
        api_key: apiKey,
        api_secret: apiSecret
      });

      toast.success('Credentials saved securely!');
      setApiKey('');
      setApiSecret('');
      setHasCredentials(true);
      
      // Redirect to dashboard after a brief delay
      setTimeout(() => {
        navigate('/dashboard');
      }, 1500);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to save credentials');
    } finally {
      setLoading(false);
    }
  };

  if (checkingCredentials) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-2 border-gray-300 border-t-gray-900 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading settings...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-6 py-12">
        
        {/* Header */}
        <div className="mb-10">
          <h1 className="text-3xl font-semibold text-gray-900 mb-2">Settings</h1>
          <p className="text-gray-600">Manage your trading configuration</p>
        </div>

        {/* Groww API Credentials Section */}
        <div className="bg-white rounded-2xl p-8 border border-gray-200 shadow-sm mb-8">
          <h2 className="text-2xl font-semibold text-gray-900 mb-2">Groww API Credentials</h2>
          <p className="text-gray-600 text-sm mb-6">Connect your Groww account to enable trading functionality</p>

          {hasCredentials && (
            <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg mb-6 text-sm">
              ✓ API credentials are saved and encrypted
            </div>
          )}

          <div className="space-y-5">
            <div>
              <label className="block text-gray-900 font-semibold mb-2 text-sm">API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Your Groww API key"
                className="w-full bg-white border border-gray-300 rounded-lg px-4 py-2.5 text-gray-900 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-400"
              />
              <p className="text-gray-600 text-xs mt-2">Get your API key from <a href="https://groww.in" target="_blank" rel="noopener noreferrer" className="text-gray-900 hover:underline">Groww dashboard</a></p>
            </div>

            <div>
              <label className="block text-gray-900 font-semibold mb-2 text-sm">API Secret</label>
              <input
                type="password"
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                placeholder="Your Groww API secret"
                className="w-full bg-white border border-gray-300 rounded-lg px-4 py-2.5 text-gray-900 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-400"
              />
            </div>

            <button
              onClick={handleSaveCredentials}
              disabled={loading}
              className="w-full bg-gray-900 hover:bg-gray-800 disabled:bg-gray-400 text-white font-semibold py-2.5 px-6 rounded-lg transition-colors"
            >
              {loading ? 'Saving...' : 'Save Credentials'}
            </button>

            {!hasCredentials && (
              <p className="text-gray-600 text-sm text-center">
                You need to add your API credentials to access trading features.
              </p>
            )}
          </div>
        </div>

        {/* Security Notice */}
        <div className="bg-blue-50 border border-blue-200 rounded-2xl p-6">
          <h3 className="text-sm font-semibold text-blue-900 mb-2">🔒 Security</h3>
          <p className="text-blue-700 text-sm">
            Your API credentials are encrypted and stored securely. They are never sent to third parties or logged.
          </p>
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
