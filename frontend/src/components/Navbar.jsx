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
    <nav className="sticky top-0 z-50 bg-white/95 backdrop-blur-xl border-b border-gray-100 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        <div className="flex justify-between items-center h-14 sm:h-16">
          
          {/* Logo */}
          <div
            onClick={() => navigate('/dashboard')}
            className="flex items-center cursor-pointer group transition-transform hover:scale-105"
          >
            <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-gradient-to-br from-gray-900 to-gray-800 flex items-center justify-center text-white font-bold shadow-md">
              G
            </div>
            <span className="ml-2 sm:ml-3 text-base sm:text-lg font-bold text-gray-900 hidden sm:block">Grow</span>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden lg:flex items-center space-x-1">
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
          <div className="flex items-center space-x-2 sm:space-x-3">
            <button
              onClick={() => navigate('/settings')}
              className="p-2 sm:p-2.5 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg sm:rounded-xl transition-all duration-200 hover:scale-110"
              title="Settings"
            >
              <svg className="w-4 h-4 sm:w-5 sm:h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>

            {/* User Menu */}
            <div className="relative">
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="flex items-center space-x-1 sm:space-x-2 px-2 sm:px-3 py-1.5 sm:py-2 rounded-lg sm:rounded-xl hover:bg-gray-100 transition-all duration-200 group"
              >
                <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white text-xs sm:text-sm font-bold shadow-md group-hover:shadow-lg transition-shadow">
                  {user?.name?.charAt(0).toUpperCase()}
                </div>
                <svg className={`w-3.5 h-3.5 sm:w-4 sm:h-4 text-gray-600 transition-transform duration-200 hidden sm:block ${menuOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                </svg>
              </button>

              {/* Dropdown */}
              {menuOpen && (
                <div className="absolute right-0 mt-2 sm:mt-3 w-48 sm:w-56 bg-white rounded-lg sm:rounded-2xl shadow-xl border border-gray-100 py-2 overflow-hidden animate-in fade-in zoom-in-95 duration-200 z-50">
                  <div className="px-3 sm:px-4 py-2 sm:py-3 border-b border-gray-100">
                    <p className="text-gray-900 font-semibold text-xs sm:text-sm">{user?.name}</p>
                    <p className="text-gray-500 text-xs mt-1 truncate">{user?.email}</p>
                  </div>
                  <button
                    onClick={() => {
                      navigate('/settings');
                      setMenuOpen(false);
                    }}
                    className="w-full text-left px-3 sm:px-4 py-2 sm:py-3 text-xs sm:text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center gap-2"
                  >
                    <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    </svg>
                    Settings
                  </button>
                  <button
                    onClick={() => {
                      handleLogout();
                      setMenuOpen(false);
                    }}
                    className="w-full text-left px-3 sm:px-4 py-2 sm:py-3 text-xs sm:text-sm text-red-600 hover:bg-red-50 transition-colors border-t border-gray-100 flex items-center gap-2"
                  >
                    <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                    </svg>
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
      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
        isActive
          ? 'bg-gray-100 text-gray-900 shadow-sm'
          : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
      }`}
    >
      {label}
    </button>
  );
}

export default Navbar;
