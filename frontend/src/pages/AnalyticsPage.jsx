import { useEffect, useState } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';
import toast from 'react-hot-toast';
import api from '../services/api';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

function AnalyticsPage() {
  const [pnlData, setPnlData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hoveredIndex, setHoveredIndex] = useState(null);

  useEffect(() => {
    fetchPnLAnalytics();
  }, []);

  const fetchPnLAnalytics = async () => {
    try {
      setLoading(true);
      const response = await api.get('/api/analytics/pnl');
      setPnlData(response.data);
    } catch (error) {
      toast.error('Failed to load analytics');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500"></div>
      </div>
    );
  }

  if (!pnlData) {
    return <div className="text-white p-8">No data available</div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-white mb-8">P&L Analytics</h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <SummaryCard
          label="Total P&L"
          value={`₹${pnlData.summary.total_pnl.toLocaleString('en-IN')}`}
          color={pnlData.summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
          icon="💰"
        />
        <SummaryCard
          label="Peak P&L"
          value={`₹${pnlData.summary.peak_pnl.toLocaleString('en-IN')}`}
          color="text-yellow-400"
          icon="📈"
        />
        <SummaryCard
          label="Capital Invested"
          value={`₹${pnlData.summary.total_capital.toLocaleString('en-IN')}`}
          color="text-blue-400"
          icon="💎"
        />
        <SummaryCard
          label="Final ROI"
          value={`${pnlData.summary.final_roi.toFixed(2)}%`}
          color={pnlData.summary.final_roi >= 0 ? 'text-green-400' : 'text-red-400'}
          icon="🎯"
        />
      </div>

      {/* Interactive Chart */}
      <div className="bg-gray-800 rounded-lg p-6 mb-8">
        <h2 className="text-xl font-semibold text-white mb-4">P&L Growth Over Time</h2>
        <div className="relative">
          <InteractivePnLChart
            data={pnlData}
            hoveredIndex={hoveredIndex}
            onHover={setHoveredIndex}
          />
        </div>
      </div>

      {/* Detailed Trade Table */}
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-xl font-semibold text-white mb-4">Trade Details</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="text-left py-2 text-gray-400">Date</th>
                <th className="text-left py-2 text-gray-400">Symbol</th>
                <th className="text-left py-2 text-gray-400">Capital</th>
                <th className="text-left py-2 text-gray-400">Profit</th>
                <th className="text-left py-2 text-gray-400">Trade ROI</th>
                <th className="text-left py-2 text-gray-400">Cumulative P&L</th>
                <th className="text-left py-2 text-gray-400">Total Capital</th>
              </tr>
            </thead>
            <tbody>
              {pnlData.trades.map((trade, idx) => (
                <tr
                  key={idx}
                  className="border-b border-gray-700 hover:bg-gray-700 cursor-pointer transition"
                  onMouseEnter={() => setHoveredIndex(idx)}
                  onMouseLeave={() => setHoveredIndex(null)}
                >
                  <td className="py-3 text-white">{trade.date}</td>
                  <td className="py-3 text-gray-300 font-semibold">{trade.symbol}</td>
                  <td className="py-3 text-gray-300">₹{trade.capital.toLocaleString('en-IN')}</td>
                  <td className={`py-3 font-semibold ${
                    trade.profit >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    ₹{trade.profit.toLocaleString('en-IN')}
                  </td>
                  <td className={`py-3 font-semibold ${
                    trade.roi >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {trade.roi.toFixed(2)}%
                  </td>
                  <td className={`py-3 font-semibold ${
                    trade.cumulative_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    ₹{trade.cumulative_pnl.toLocaleString('en-IN')}
                  </td>
                  <td className="py-3 text-blue-400 font-semibold">
                    ₹{trade.capital_invested_total.toLocaleString('en-IN')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function InteractivePnLChart({ data, hoveredIndex, onHover }) {
  const chartOptions = {
    responsive: true,
    maintainAspectRatio: true,
    interaction: {
      mode: 'index',
      intersect: false,
    },
    plugins: {
      legend: {
        labels: {
          color: '#9CA3AF',
          font: {
            size: 12,
          }
        },
        position: 'top',
      },
      tooltip: {
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        borderColor: '#6366F1',
        borderWidth: 1,
        padding: 12,
        titleColor: '#FFF',
        bodyColor: '#FFF',
        titleFont: { size: 13, weight: 'bold' },
        bodyFont: { size: 12 },
        callbacks: {
          title: (context) => {
            const idx = context[0].dataIndex;
            return `${data.dates[idx]}`;
          },
          label: (context) => {
            const idx = context.dataIndex;
            const trade = data.trades[idx];
            
            if (context.dataset.label === 'Cumulative P&L (₹)') {
              return [
                `P&L: ₹${data.cumulative_pnl_amount[idx].toLocaleString('en-IN')}`,
                `Capital Invested: ₹${data.capital_invested[idx].toLocaleString('en-IN')}`,
                `ROI: ${data.roi_percentage[idx].toFixed(2)}%`,
                `Trade: ${trade.symbol}`,
                `Trade Profit: ₹${trade.profit.toLocaleString('en-IN')}`
              ];
            }
            
            if (context.dataset.label === 'Peak P&L (₹)') {
              return `Peak: ₹${data.peak_pnl_amount[idx].toLocaleString('en-IN')}`;
            }
            
            return [];
          },
          afterLabel: (context) => {
            const idx = context.dataIndex;
            const trade = data.trades[idx];
            return `Symbol: ${trade.symbol}`;
          }
        }
      }
    },
    scales: {
      x: {
        stacked: false,
        grid: {
          color: '#374151',
          drawBorder: false,
        },
        ticks: {
          color: '#9CA3AF',
          font: {
            size: 11,
          }
        }
      },
      y: {
        stacked: false,
        grid: {
          color: '#374151',
          drawBorder: false,
        },
        ticks: {
          color: '#9CA3AF',
          font: {
            size: 11,
          },
          callback: function (value) {
            return '₹' + value.toLocaleString('en-IN');
          }
        }
      }
    }
  };

  const chartData = {
    labels: data.dates,
    datasets: [
      {
        label: 'Cumulative P&L (₹)',
        data: data.cumulative_pnl_amount,
        borderColor: '#10B981',
        backgroundColor: 'rgba(16, 185, 129, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.4,
        pointRadius: 4,
        pointBackgroundColor: (context) =>
          hoveredIndex === context.dataIndex ? '#FBBF24' : '#10B981',
        pointBorderColor: '#fff',
        pointBorderWidth: 2,
        pointHoverRadius: 6,
      },
      {
        label: 'Peak P&L (₹)',
        data: data.peak_pnl_amount,
        borderColor: '#F59E0B',
        backgroundColor: 'transparent',
        borderWidth: 2,
        fill: false,
        tension: 0.4,
        pointRadius: 3,
        pointBackgroundColor: '#F59E0B',
        pointBorderColor: '#fff',
        pointBorderWidth: 1,
        pointHoverRadius: 5,
        borderDash: [5, 5],
      },
    ]
  };

  return (
    <div onMouseMove={(e) => {
      // Handle hover for better interactivity
    }}>
      <Line data={chartData} options={chartOptions} height={100} />
      
      {/* Hover Info Box */}
      {hoveredIndex !== null && (
        <div className="mt-4 p-4 bg-gray-700 rounded-lg border border-indigo-500">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <InfoItem
              label="Date"
              value={data.dates[hoveredIndex]}
            />
            <InfoItem
              label="Cumulative P&L"
              value={`₹${data.cumulative_pnl_amount[hoveredIndex].toLocaleString('en-IN')}`}
              color="text-green-400"
            />
            <InfoItem
              label="Capital Invested"
              value={`₹${data.capital_invested[hoveredIndex].toLocaleString('en-IN')}`}
              color="text-blue-400"
            />
            <InfoItem
              label="ROI"
              value={`${data.roi_percentage[hoveredIndex].toFixed(2)}%`}
              color="text-yellow-400"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ label, value, color, icon }) {
  return (
    <div className="bg-gray-700 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-gray-400 text-sm mb-1">{label}</p>
          <p className={`text-2xl font-bold ${color}`}>{value}</p>
        </div>
        <div className="text-3xl">{icon}</div>
      </div>
    </div>
  );
}

function InfoItem({ label, value, color = 'text-white' }) {
  return (
    <div>
      <p className="text-gray-400 text-sm mb-1">{label}</p>
      <p className={`font-semibold ${color}`}>{value}</p>
    </div>
  );
}

export default AnalyticsPage;
