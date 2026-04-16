import { useEffect, useState } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js';
import toast from 'react-hot-toast';
import api from '../services/api';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend
);

function PnLChart({ height = 300 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hoveredIndex, setHoveredIndex] = useState(null);

  useEffect(() => {
    fetchPnLData();
  }, []);

  const fetchPnLData = async () => {
    try {
      const response = await api.get('/api/analytics/pnl');
      setData(response.data);
    } catch (error) {
      console.error('Failed to load P&L data');
    } finally {
      setLoading(false);
    }
  };

  if (loading || !data) {
    return (
      <div className="w-full h-64 flex items-center justify-center bg-gray-700 rounded-lg">
        <p className="text-gray-400">Loading chart...</p>
      </div>
    );
  }

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: {
          color: '#9CA3AF',
          font: { size: 10 }
        }
      },
      tooltip: {
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        borderColor: '#6366F1',
        borderWidth: 1,
        padding: 10,
        titleColor: '#FFF',
        bodyColor: '#FFF',
        titleFont: { size: 12, weight: 'bold' },
        bodyFont: { size: 11 },
        callbacks: {
          title: (context) => {
            return data.dates[context[0].dataIndex];
          },
          label: (context) => {
            const idx = context.dataIndex;
            if (context.dataset.label === 'Cumulative P&L (₹)') {
              return [
                `P&L: ₹${data.cumulative_pnl_amount[idx].toLocaleString('en-IN')}`,
                `Capital: ₹${data.capital_invested[idx].toLocaleString('en-IN')}`,
                `ROI: ${data.roi_percentage[idx].toFixed(2)}%`
              ];
            }
            if (context.dataset.label === 'Peak P&L (₹)') {
              return `Peak: ₹${data.peak_pnl_amount[idx].toLocaleString('en-IN')}`;
            }
            return [];
          }
        }
      }
    },
    scales: {
      x: {
        grid: {
          color: '#374151',
          drawBorder: false,
        },
        ticks: {
          color: '#9CA3AF',
          font: { size: 9 },
          maxTicksLimit: 6
        }
      },
      y: {
        grid: {
          color: '#374151',
          drawBorder: false,
        },
        ticks: {
          color: '#9CA3AF',
          font: { size: 9 },
          callback: function (value) {
            if (value >= 1000000) {
              return '₹' + (value / 1000000).toFixed(1) + 'M';
            } else if (value >= 1000) {
              return '₹' + (value / 1000).toFixed(0) + 'K';
            }
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
        pointRadius: 3,
        pointBackgroundColor: '#10B981',
        pointBorderColor: '#fff',
        pointBorderWidth: 1,
        pointHoverRadius: 5,
      },
      {
        label: 'Peak P&L (₹)',
        data: data.peak_pnl_amount,
        borderColor: '#F59E0B',
        backgroundColor: 'transparent',
        borderWidth: 2,
        fill: false,
        tension: 0.4,
        pointRadius: 2,
        pointBackgroundColor: '#F59E0B',
        borderDash: [5, 5],
      },
    ]
  };

  return (
    <div className="w-full">
      <Line data={chartData} options={chartOptions} height={height} />
      
      {/* Info Box when hovering */}
      {hoveredIndex !== null && (
        <div className="mt-3 p-3 bg-gray-700 rounded border border-indigo-500">
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <p className="text-gray-400">P&L</p>
              <p className="text-green-400 font-semibold">
                ₹{data.cumulative_pnl_amount[hoveredIndex].toLocaleString('en-IN')}
              </p>
            </div>
            <div>
              <p className="text-gray-400">Capital</p>
              <p className="text-blue-400 font-semibold">
                ₹{data.capital_invested[hoveredIndex].toLocaleString('en-IN')}
              </p>
            </div>
            <div>
              <p className="text-gray-400">ROI</p>
              <p className="text-yellow-400 font-semibold">
                {data.roi_percentage[hoveredIndex].toFixed(2)}%
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PnLChart;
