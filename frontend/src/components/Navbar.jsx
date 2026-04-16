import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import useAuthStore from '../store/authStore';

function Navbar({ user }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout } = useAuthStore();
  const [menuOpen, setMenuOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate('/');
  };

  const isActive = (path) => location.pathname === path;

  return (
    <nav className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-6">
        <div className="flex justify-between items-center h-14">
          
          {/* Logo */}
          <div
            onClick={() => navigate('/dashboard')}
            className="flex items-center cursor-pointer group"
          >
            <span className="text-base font-semibold text-gray-900">Grow</span>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden md:flex space-x-8">
            <NavLink
              label="Dashboard"
              isActive={isActive('/dashboard')}
              onClick={() => navigate('/dashboard')}
            />
            <NavLink
              label="Trading"
              isActive={isActive('/trading')}
              onClick={() => navigate('/trading')}
            />
            <NavLink
              label="Analytics"
              isActive={isActive('/analytics')}
              onClick={() => navigate('/analytics')}
            />
            <NavLink
              label="Backtest"
              isActive={isActive('/backtesting')}
              onClick={() => navigate('/backtesting')}
            />
            {user?.is_admin && (
              <NavLink
                label="Admin"
                isActive={isActive('/admin')}
                onClick={() => navigate('/admin')}
              />
            )}
          </div>

          {/* Right Section */}
          <div className="flex items-center space-x-4">
            <button
              onClick={() => navigate('/settings')}
              className="p-2 text-gray-600 hover:text-gray-900 rounded-lg hover:bg-gray-100 transition-colors"
              title="Settings"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>

            {/* User Menu */}
            <div className="relative">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="flex items-center space-x-2.5 px-3 py-2 rounded-lg hover:bg-gray-100 transition-colors"
              >
                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-gray-900 to-gray-700 flex items-center justify-center text-white text-xs font-semibold">
                  {user?.name?.charAt(0).toUpperCase()}
                </div>
              </button>

              {/* Dropdown */}
              {menuOpen && (
                <div className="absolute right-0 mt-2 w-48 bg-white rounded-xl shadow-lg border border-gray-200 py-1 overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <p className="text-gray-900 font-semibold text-sm">{user?.name}</p>
                    <p className="text-gray-500 text-xs mt-1">{user?.email}</p>
                  </div>
                  <button
                    onClick={() => {
                      navigate('/settings');
                      setMenuOpen(false);
                    }}
                    className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    Settings
                  </button>
                  <button
                    onClick={() => {
                      handleLogout();
                      setMenuOpen(false);
                    }}
                    className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors border-t border-gray-100"
                  >
                    Sign Out
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}

function NavLink({ label, isActive, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`text-sm font-medium transition-colors ${
        isActive
          ? 'text-gray-900 border-b-2 border-gray-900 pb-3'
          : 'text-gray-600 hover:text-gray-900 pb-3'
      }`}
    >
      {label}
    </button>
  );
}

export default Navbar;
