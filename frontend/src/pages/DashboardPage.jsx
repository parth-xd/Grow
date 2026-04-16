import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';
import useAuthStore from '../store/authStore';
import PnLChart from '../components/PnLChart';

function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const [stats, setStats] = useState(null);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);

      // Fetch statistics
      const statsRes = await api.get('/api/trades/journal/stats');
      setStats(statsRes.data);

      // Fetch recent trades
      const tradesRes = await api.get('/api/trades/journal?limit=10');
      setTrades(tradesRes.data.trades || []);

    } catch (error) {
      toast.error('Failed to load dashboard data');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Welcome Header */}
      <div className="mb-10">
        <h1 className="text-4xl font-bold text-gray-900">Welcome, {user?.name?.split(' ')[0]}!</h1>
        <p className="text-gray-500 mt-2 text-lg">Track your trading performance at a glance</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <StatCard
          label="Total Trades"
          value={stats?.total_trades || 0}
          icon="📊"
        />
        <StatCard
          label="Win Rate"
          value={`${stats?.win_rate?.toFixed(2) || 0}%`}
          icon="🎯"
        />
        <StatCard
          label="Net P&L"
          value={`₹${stats?.net_pnl?.toFixed(2) || 0}`}
          color={stats?.net_pnl >= 0 ? 'text-green-600' : 'text-red-600'}
          icon="💰"
        />
        <StatCard
          label="Return"
          value={`${stats?.return_percentage?.toFixed(2) || 0}%`}
          color={stats?.return_percentage >= 0 ? 'text-green-600' : 'text-red-600'}
          icon="📈"
        />
      </div>

      {/* P&L Chart */}
      <div className="card p-8 mb-8">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-2xl font-semibold text-gray-900">P&L Growth</h2>
            <p className="text-gray-500 text-sm mt-1">Your cumulative profit and loss over time</p>
          </div>
          <button
            onClick={() => navigate('/analytics')}
            className="text-blue-500 hover:text-blue-600 font-medium text-sm transition-colors"
          >
            View Detailed Analytics →
          </button>
        </div>
        <PnLChart height={250} />
      </div>

      {/* Recent Trades */}
      <div className="card p-8">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h2 className="text-2xl font-semibold text-gray-900">Recent Trades</h2>
            <p className="text-gray-500 text-sm mt-1">Your latest trading activity</p>
          </div>
          <button
            onClick={() => navigate('/trading')}
            className="btn-primary"
          >
            View All
          </button>
        </div>

        {trades.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 text-gray-600 font-semibold">Symbol</th>
                  <th className="text-left py-3 text-gray-600 font-semibold">Side</th>
                  <th className="text-left py-3 text-gray-600 font-semibold">Entry Price</th>
                  <th className="text-left py-3 text-gray-600 font-semibold">Exit Price</th>
                  <th className="text-left py-3 text-gray-600 font-semibold">P&L</th>
                  <th className="text-left py-3 text-gray-600 font-semibold">Return</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade) => (
                  <tr key={trade.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="py-4 text-gray-900 font-semibold">{trade.symbol}</td>
                    <td className="py-4">
                      <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                        trade.side === 'BUY'
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}>
                        {trade.side}
                      </span>
                    </td>
                    <td className="py-4 text-gray-600">₹{trade.entry_price?.toFixed(2)}</td>
                    <td className="py-4 text-gray-600">₹{trade.exit_price?.toFixed(2)}</td>
                    <td className={`py-4 font-semibold ${
                      trade.pnl >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}>
                      ₹{trade.pnl?.toFixed(2)}
                    </td>
                    <td className={`py-4 font-semibold ${
                      trade.pnl_percentage >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}>
                      {trade.pnl_percentage?.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-center py-12">No trades yet</p>
        )}
      </div>

      {/* Action Buttons */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-8">
        <button
          onClick={() => navigate('/trading')}
          className="btn-primary py-3 text-base font-semibold"
        >
          Execute Trade
        </button>
        <button
          onClick={() => navigate('/backtesting')}
          className="btn-secondary py-3 text-base font-semibold"
        >
          Run Backtest
        </button>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon, color = 'text-gray-900' }) {
  return (
    <div className="card p-6 hover:shadow-md transition-shadow">
      <div className="text-4xl mb-3">{icon}</div>
      <p className="text-gray-600 text-sm font-medium mb-2">{label}</p>
      <p className={`text-3xl font-semibold ${color}`}>{value}</p>
    </div>
  );
}

export default DashboardPage;
