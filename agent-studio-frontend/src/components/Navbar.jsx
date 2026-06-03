import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import FeedbackModal from './ui/FeedbackModal';

export default function Navbar() {
  const { user, logout } = useAuth();
  const [showDropdown, setShowDropdown] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);

  const handleLogout = () => {
    logout();
    setShowDropdown(false);
  };

  const getInitials = () => {
    if (user?.firstName && user?.lastName) {
      return `${user.firstName[0]}${user.lastName[0]}`.toUpperCase();
    }
    if (user?.firstName) {
      return user.firstName[0].toUpperCase();
    }
    if (user?.email) {
      return user.email[0].toUpperCase();
    }
    return 'U';
  };

  return (
    <>
      <header className="fixed top-0 left-0 right-0 h-14 sm:h-16 bg-white border-b border-gray-200 z-[1000] shadow-sm">
        <div className="flex items-center justify-between h-full px-4 sm:px-6 lg:px-8 max-w-full">
          {/* Left Section */}
          <div className="flex items-center gap-3 sm:gap-4 lg:gap-6">
            <div className="flex flex-col items-end leading-tight">
              <span className="font-bold text-lg sm:text-xl lg:text-2xl text-gray-900 whitespace-nowrap">ApexOS</span>
   
            </div>
          </div>

          {/* Right Section */}
          <div className="flex items-center gap-2 sm:gap-3 relative">
            {/* Feedback Button */}
            <button
              onClick={() => setShowFeedback(true)}
              className="h-9 sm:h-10 px-2.5 sm:px-3 rounded-full border border-gray-200 bg-white flex items-center justify-center gap-1.5 text-gray-500 hover:text-[#A32020] hover:border-[#A32020]/30 hover:bg-[#A32020]/5 transition-all cursor-pointer shadow-sm"
              title="Share feedback"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                <path d="M8 10h.01M12 10h.01M16 10h.01" />
              </svg>
              <span className="hidden sm:inline text-xs font-medium">Feedback</span>
            </button>

            {/* User Avatar */}
            <div className="relative">
              <div
                className="w-9 h-9 sm:w-10 sm:h-10 rounded-full bg-primary flex items-center justify-center text-white font-semibold text-sm sm:text-base cursor-pointer hover:bg-primary-hover transition-colors shadow-sm"
                title={user?.email || 'User Account'}
                onClick={() => setShowDropdown(!showDropdown)}
              >
                {getInitials()}
              </div>

              {/* Dropdown Menu */}
              {showDropdown && (
                <>
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setShowDropdown(false)}
                  />
                  <div className="absolute right-0 mt-2 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-20">
                    <div className="p-4 border-b border-gray-200">
                      <p className="font-semibold text-sm text-gray-900">
                        {user?.firstName && user?.lastName
                          ? `${user.firstName} ${user.lastName}`
                          : user?.firstName || 'User'}
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        {user?.email}
                      </p>
                    </div>
                    <div className="p-2">
                      <button
                        onClick={handleLogout}
                        className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
                      >
                        Sign out
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      <FeedbackModal isOpen={showFeedback} onClose={() => setShowFeedback(false)} />
    </>
  );
}
