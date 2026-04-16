import { useEffect, useState } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';

function AdminPage() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      const response = await api.get('/api/admin/users');
      setUsers(response.data.users || []);
    } catch (error) {
      toast.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="text-white p-8">Loading...</div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-white mb-8">Admin Dashboard</h1>

      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-xl font-semibold text-white mb-4">Users</h2>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="text-left py-2 text-gray-400">Email</th>
                <th className="text-left py-2 text-gray-400">Name</th>
                <th className="text-left py-2 text-gray-400">Trades</th>
                <th className="text-left py-2 text-gray-400">Status</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-gray-700 hover:bg-gray-700">
                  <td className="py-3 text-white">{user.email}</td>
                  <td className="py-3 text-gray-300">{user.name}</td>
                  <td className="py-3 text-gray-300">{user.trade_count || 0}</td>
                  <td className="py-3">
                    <span className={`px-2 py-1 rounded text-xs font-semibold ${
                      user.is_active
                        ? 'bg-green-900 text-green-200'
                        : 'bg-red-900 text-red-200'
                    }`}>
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-gray-400 mt-4">Total users: {users.length}</p>
      </div>
    </div>
  );
}

export default AdminPage;
