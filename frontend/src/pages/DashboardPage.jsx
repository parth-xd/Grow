import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';
import useAuthStore from '../store/authStore';
import PnLChart from '../components/PnLChart';
import CustomCursor from '../components/CustomCursor';

function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const [stats, setStats] = useState(null);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [hasCredentials, setHasCredentials] = useState(false);
  const [checkingCredentials, setCheckingCredentials] = useState(true);

  useEffect(() => {
    checkCredentialsAndFetch();
  }, []);

  const checkCredentialsAndFetch = async () => {
    try {
      // Check if user has API credentials
      const credResponse = await api.get('/api/credentials/status');
      setHasCredentials(credResponse.data.has_credentials);
      setCheckingCredentials(false);

      // Only fetch data if they have credentials
      if (credResponse.data.has_credentials) {
        fetchDashboardData();
      } else {
        setLoading(false);
      }
    } catch (error) {
      console.error('Failed to check credentials:', error);
      setCheckingCredentials(false);
      setLoading(false);
    }
  };

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      const statsRes = await api.get('/api/trades/journal/stats');
      setStats(statsRes.data);
      const tradesRes = await api.get('/api/trades/journal?limit=10');
      setTrades(tradesRes.data.trades || []);
    } catch (error) {
      toast.error('Failed to load dashboard data');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  if (checkingCredentials || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-2 border-gray-300 border-t-gray-900 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading your dashboard...</p>
        </div>
      </div>
    );
  }

  // Show setup message if no credentials
  if (!hasCredentials) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-2xl mx-auto px-6 py-20">
          <div className="text-center">
            <h1 className="text-4xl font-semibold text-gray-900 mb-4">Welcome, {user?.name?.split(' ')[0]}! 👋</h1>
            <p className="text-lg text-gray-600 mb-8">To get started with trading, you need to connect your Groww account.</p>
            
            <div className="bg-white rounded-2xl p-8 border border-gray-200 shadow-sm mb-8">
              <div className="text-5xl mb-4">🔗</div>
              <h2 className="text-2xl font-semibold text-gray-900 mb-3">Connect Your Groww Account</h2>
              <p className="text-gray-600 mb-6">Add your Groww API credentials to enable trading features and access your portfolio data.</p>
              <button
                onClick={() => navigate('/settings')}
                className="bg-gray-900 hover:bg-gray-800 text-white font-semibold py-3 px-8 rounded-lg transition-colors inline-block"
              >
                Add API Credentials
              </button>
            </div>

            <div className="bg-blue-50 border border-blue-200 rounded-2xl p-6 text-left">
              <h3 className="text-sm font-semibold text-blue-900 mb-3">ℹ️ How to get your API credentials:</h3>
              <ol className="text-blue-700 text-sm space-y-2 list-decimal list-inside">
                <li>Go to <a href="https://groww.in" target="_blank" rel="noopener noreferrer" className="underline">Groww.in</a></li>
                <li>Navigate to Developer Settings or API section</li>
                <li>Create a new API key with trading permissions</li>
                <li>Copy your API Key and API Secret</li>
                <li>Return here and paste them securely</li>
              </ol>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-6 py-12">
        
        {/* Welcome Section */}
        <div className="mb-12">
          <h1 className="text-5xl font-semibold text-gray-900">Hi, {user?.name?.split(' ')[0]}</h1>
          <p className="text-gray-500 mt-2 text-lg">Here's your trading overview</p>
        </div>

        {/* Stats Grid - Apple Style */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
          <StatCard
            label="Total Trades"
            value={stats?.total_trades || 0}
            subtext="this month"
          />
          <StatCard
            label="Win Rate"
            value={`${stats?.win_rate?.toFixed(1) || 0}%`}
            subtext="success rate"
          />
          <StatCard
            label="Net P&L"
            value={`₹${Math.abs(stats?.net_pnl || 0).toFixed(0)}`}
            subtext={stats?.net_pnl >= 0 ? '↑ Profit' : '↓ Loss'}
            isPositive={stats?.net_pnl >= 0}
          />
          <StatCard
            label="Return"
            value={`${stats?.return_percentage?.toFixed(1) || 0}%`}
            subtext="total return"
            isPositive={stats?.return_percentage >= 0}
          />
        </div>

        {/* Charts Section */}
        <div className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100 mb-12">
          <div className="flex justify-between items-start mb-8">
            <div>
              <h2 className="text-2xl font-semibold text-gray-900">Performance</h2>
              <p className="text-gray-500 mt-1">Your cumulative P&L over time</p>
            </div>
            <button
              onClick={() => navigate('/analytics')}
              className="text-gray-900 hover:text-gray-600 font-medium text-sm transition-colors"
            >
              Analytics →
            </button>
          </div>
          <PnLChart height={300} />
        </div>

        {/* Recent Trades */}
        <div className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100">
          <div className="flex justify-between items-start mb-8">
            <div>
              <h2 className="text-2xl font-semibold text-gray-900">Recent Activity</h2>
              <p className="text-gray-500 mt-1">Your latest trades</p>
            </div>
            <button
              onClick={() => navigate('/trading')}
              className="text-gray-900 hover:text-gray-600 font-medium text-sm transition-colors"
            >
              View All →
            </button>
          </div>

          {trades.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left py-4 text-gray-600 font-semibold">Symbol</th>
                    <th className="text-left py-4 text-gray-600 font-semibold">Type</th>
                    <th className="text-left py-4 text-gray-600 font-semibold">Entry</th>
                    <th className="text-left py-4 text-gray-600 font-semibold">Exit</th>
                    <th className="text-left py-4 text-gray-600 font-semibold">P&L</th>
                    <th className="text-left py-4 text-gray-600 font-semibold">Return</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade) => (
                    <tr key={trade.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                      <td className="py-5 text-gray-900 font-semibold">{trade.symbol}</td>
                      <td className="py-5">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          trade.side === 'BUY'
                            ? 'bg-green-50 text-green-700'
                            : 'bg-red-50 text-red-700'
                        }`}>
                          {trade.side === 'BUY' ? '📈' : '📉'} {trade.side}
                        </span>
                      </td>
                      <td className="py-5 text-gray-600">₹{trade.entry_price?.toFixed(2)}</td>
                      <td className="py-5 text-gray-600">₹{trade.exit_price?.toFixed(2)}</td>
                      <td className={`py-5 font-semibold ${
                        trade.pnl >= 0 ? 'text-green-600' : 'text-red-600'
                      }`}>
                        {trade.pnl >= 0 ? '+' : ''}₹{trade.pnl?.toFixed(0)}
                      </td>
                      <td className={`py-5 font-semibold ${
                        trade.pnl_percentage >= 0 ? 'text-green-600' : 'text-red-600'
                      }`}>
                        {trade.pnl_percentage >= 0 ? '+' : ''}{trade.pnl_percentage?.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12">
              <p className="text-gray-500 text-lg">No trades yet</p>
              <button
                onClick={() => navigate('/trading')}
                className="text-gray-900 hover:text-gray-600 font-medium mt-4 transition-colors"
              >
                Start trading →
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, subtext, isPositive }) {
  return (
    <div className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
      <p className="text-gray-600 text-sm font-medium">{label}</p>
      <div className="mt-3">
        <p className={`text-3xl font-semibold ${
          isPositive !== undefined 
            ? (isPositive ? 'text-green-600' : 'text-red-600')
            : 'text-gray-900'
        }`}>
          {value}
        </p>
        <p className="text-gray-500 text-xs mt-2">{subtext}</p>
      </div>
    </div>
  );
}

export default DashboardPage;
