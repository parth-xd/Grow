import { useState } from 'react';
import toast from 'react-hot-toast';
import api from '../services/api';

function TradingPage() {
  const [symbol, setSymbol] = useState('INFY');
  const [side, setSide] = useState('BUY');
  const [quantity, setQuantity] = useState(1);
  const [type, setType] = useState('PAPER');
  const [loading, setLoading] = useState(false);

  const handleExecuteTrade = async () => {
    if (!symbol || !quantity) {
      toast.error('Please fill all fields');
      return;
    }

    setLoading(true);
    try {
      await api.post('/api/trades/execute', {
        symbol,
        side,
        quantity: parseInt(quantity),
        type
      });

      toast.success('Trade executed successfully!');
      setSymbol('');
      setQuantity(1);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to execute trade');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-white mb-8">Execute Trade</h1>

      <div className="bg-gray-800 rounded-lg p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Symbol */}
          <div>
            <label className="block text-white font-semibold mb-2">Symbol</label>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="e.g., INFY"
              className="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2 text-white"
            />
          </div>

          {/* Quantity */}
          <div>
            <label className="block text-white font-semibold mb-2">Quantity</label>
            <input
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              min="1"
              className="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2 text-white"
            />
          </div>

          {/* Side */}
          <div>
            <label className="block text-white font-semibold mb-2">Side</label>
            <select
              value={side}
              onChange={(e) => setSide(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2 text-white"
            >
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
            </select>
          </div>

          {/* Type */}
          <div>
            <label className="block text-white font-semibold mb-2">Type</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2 text-white"
            >
              <option value="PAPER">Paper Trading (Demo)</option>
              <option value="REAL">Real Trading</option>
            </select>
          </div>
        </div>

        <button
          onClick={handleExecuteTrade}
          disabled={loading}
          className="mt-6 w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 text-white font-semibold py-3 rounded-lg transition"
        >
          {loading ? 'Executing...' : 'Execute Trade'}
        </button>
      </div>
    </div>
  );
}

export default TradingPage;
