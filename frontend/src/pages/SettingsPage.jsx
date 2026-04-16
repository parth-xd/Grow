import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import api from '../services/api';

function SettingsPage() {
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [loading, setLoading] = useState(false);
  const [hasCredentials, setHasCredentials] = useState(false);

  useEffect(() => {
    checkCredentials();
  }, []);

  const checkCredentials = async () => {
    try {
      const response = await api.get('/api/users/api-credentials');
      setHasCredentials(response.data.has_credentials);
    } catch (error) {
      console.error('Failed to check credentials');
    }
  };

  const handleSaveCredentials = async () => {
    if (!apiKey || !apiSecret) {
      toast.error('Please fill all fields');
      return;
    }

    setLoading(true);
    try {
      await api.post('/api/users/api-credentials', {
        api_key: apiKey,
        api_secret: apiSecret
      });

      toast.success('Credentials saved securely!');
      setApiKey('');
      setApiSecret('');
      setHasCredentials(true);
    } catch (error) {
      toast.error('Failed to save credentials');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-white mb-8">Settings</h1>

      {/* Groww API Credentials */}
      <div className="bg-gray-800 rounded-lg p-6 mb-6">
        <h2 className="text-xl font-semibold text-white mb-4">Groww API Credentials</h2>

        {hasCredentials && (
          <div className="bg-green-900 border border-green-700 text-green-100 px-4 py-3 rounded mb-4">
            ✓ API credentials are saved and encrypted
          </div>
        )}

        <div className="mb-4">
          <label className="block text-white font-semibold mb-2">API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Your Groww API key"
            className="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2 text-white"
          />
          <p className="text-gray-400 text-sm mt-1">Get your API key from Groww dashboard</p>
        </div>

        <div className="mb-4">
          <label className="block text-white font-semibold mb-2">API Secret</label>
          <input
            type="password"
            value={apiSecret}
            onChange={(e) => setApiSecret(e.target.value)}
            placeholder="Your Groww API secret"
            className="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2 text-white"
          />
        </div>

        <button
          onClick={handleSaveCredentials}
          disabled={loading}
          className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 text-white font-semibold py-2 px-6 rounded-lg"
        >
          {loading ? 'Saving...' : 'Save Credentials'}
        </button>
      </div>

      {/* Trading Preferences */}
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-xl font-semibold text-white mb-4">Trading Preferences</h2>
        <label className="flex items-center text-white">
          <input type="checkbox" defaultChecked className="mr-2" />
          Paper trading enabled
        </label>
        <label className="flex items-center text-white mt-2">
          <input type="checkbox" className="mr-2" />
          Real trading enabled
        </label>
      </div>
    </div>
  );
}

export default SettingsPage;
