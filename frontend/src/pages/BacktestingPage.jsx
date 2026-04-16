import { useEffect, useState } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';

function BacktestingPage() {
  const [loading, setLoading] = useState(false);

  const runBacktest = async () => {
    setLoading(true);
    try {
      const response = await api.post('/api/backtesting/run', {});
      toast.success('Backtest completed!');
    } catch (error) {
      toast.error('Backtest failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-white mb-8">Backtesting</h1>
      <div className="bg-gray-800 rounded-lg p-6">
        <p className="text-gray-400 mb-6">Test your trading strategy on historical data</p>
        <button
          onClick={runBacktest}
          disabled={loading}
          className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 text-white font-semibold py-3 px-6 rounded-lg"
        >
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </div>
    </div>
  );
}

export default BacktestingPage;
