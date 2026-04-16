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
    <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-6">
        <div className="flex justify-between items-center h-16">
          {/* Logo */}
          <div
            onClick={() => navigate('/dashboard')}
            className="flex items-center cursor-pointer group"
          >
            <span className="text-xl font-semibold text-gray-900 transition-colors group-hover:text-blue-500">Groww</span>
            <span className="text-xs ml-2.5 bg-blue-100 text-blue-700 px-2.5 py-1 rounded-full font-medium">
              AI
            </span>
          </div>

          {/* Desktop Menu */}
          <div className="hidden md:flex space-x-1">
            <NavLink
              label="Dashboard"
              path="/dashboard"
              isActive={isActive('/dashboard')}
              onClick={() => navigate('/dashboard')}
            />
            <NavLink
              label="Trading"
              path="/trading"
              isActive={isActive('/trading')}
              onClick={() => navigate('/trading')}
            />
            <NavLink
              label="Backtest"
              path="/backtesting"
              isActive={isActive('/backtesting')}
              onClick={() => navigate('/backtesting')}
            />
            <NavLink
              label="Analytics"
              path="/analytics"
              isActive={isActive('/analytics')}
              onClick={() => navigate('/analytics')}
            />
            {user?.is_admin && (
              <NavLink
                label="Admin"
                path="/admin"
                isActive={isActive('/admin')}
                onClick={() => navigate('/admin')}
              />
            )}
          </div>

          {/* User Menu */}
          <div className="flex items-center space-x-3">
            <button
              onClick={() => navigate('/settings')}
              className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              title="Settings"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>

            <div className="relative">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="flex items-center space-x-2.5 rounded-lg hover:bg-gray-100 px-3 py-2 transition-colors"
              >
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center text-white text-sm font-semibold">
                  {user?.name?.charAt(0).toUpperCase()}
                </div>
                <span className="hidden sm:inline text-sm font-medium text-gray-700">{user?.name?.split(' ')[0]}</span>
                <svg className={`w-4 h-4 text-gray-600 transition-transform ${menuOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                </svg>
              </button>

              {/* Dropdown Menu */}
              {menuOpen && (
                <div className="absolute right-0 mt-2 w-56 bg-white rounded-2xl shadow-lg border border-gray-200 py-2 overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <p className="text-gray-900 font-semibold text-sm">{user?.name}</p>
                    <p className="text-gray-500 text-xs mt-1">{user?.email}</p>
                  </div>
                  <button
                    onClick={() => {
                      navigate('/settings');
                      setMenuOpen(false);
                    }}
                    className="block w-full text-left px-4 py-2.5 text-gray-700 hover:bg-gray-50 text-sm font-medium transition-colors"
                  >
                    Settings
                  </button>
                  <button
                    onClick={() => {
                      handleLogout();
                      setMenuOpen(false);
                    }}
                    className="block w-full text-left px-4 py-2.5 text-red-600 hover:bg-red-50 text-sm font-medium transition-colors border-t border-gray-100"
                  >
                    Sign Out
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Mobile Menu */}
        <div className="md:hidden pb-4 space-y-1">
          <MobileNavLink
            label="Dashboard"
            isActive={isActive('/dashboard')}
            onClick={() => navigate('/dashboard')}
          />
          <MobileNavLink
            label="Trading"
            isActive={isActive('/trading')}
            onClick={() => navigate('/trading')}
          />
          <MobileNavLink
            label="Backtest"
            isActive={isActive('/backtesting')}
            onClick={() => navigate('/backtesting')}
          />
          <MobileNavLink
            label="Analytics"
            isActive={isActive('/analytics')}
            onClick={() => navigate('/analytics')}
          />
          {user?.is_admin && (
            <MobileNavLink
              label="Admin"
              isActive={isActive('/admin')}
              onClick={() => navigate('/admin')}
            />
          )}
        </div>
      </div>
    </nav>
  );
}

function NavLink({ label, path, isActive, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
        isActive
          ? 'bg-blue-50 text-blue-600'
          : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  );
}

function MobileNavLink({ label, isActive, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`block w-full text-left px-4 py-2.5 text-sm font-medium rounded-lg transition-colors ${
        isActive
          ? 'bg-blue-50 text-blue-600'
          : 'text-gray-700 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  );
}

export default Navbar;
