/**
 * Authentication Context
 *
 * Provides global authentication state and methods for the application.
 * Access tokens are held in memory; refresh tokens live in HttpOnly cookies.
 */
import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import * as authClient from '../api/auth-client.js';

function sanitizeText(value) {
  if (typeof value !== 'string') return value;
  return value.replace(/[<>"'&]/g, c => ({'<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','&':'&amp;'})[c]);
}

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const initAuth = async () => {
      const params = new URLSearchParams(window.location.search);
      const oauthCode = params.get('code');
      const oauthError = params.get('error');

      if (oauthError) {
        setError(sanitizeText(oauthError));
        window.history.replaceState({}, '', '/');
        setLoading(false);
        return;
      }

      // OAuth return: exchange one-time code for tokens
      if (oauthCode) {
        window.history.replaceState({}, '', '/');
        try {
          await authClient.exchangeOAuthCode(oauthCode);
          const currentUser = await authClient.getMe();
          setUser(currentUser);
        } catch {
          authClient.clearAuth();
          setUser(null);
        }
        setLoading(false);
        return;
      }

      // Normal load: try to restore session via refresh cookie
      try {
        await authClient.refreshAccessToken();
        const currentUser = await authClient.getMe();
        setUser(currentUser);
      } catch {
        authClient.clearAuth();
        setUser(null);
      }

      setLoading(false);
    };

    initAuth();

    const handleLogout = () => {
      setUser(null);
      setError(null);
    };

    window.addEventListener('auth:logout', handleLogout);
    return () => window.removeEventListener('auth:logout', handleLogout);
  }, []);

  const register = useCallback(async (userData) => {
    try {
      setError(null);
      setLoading(true);
      await authClient.register(userData);
      const u = authClient.getStoredUser();
      setUser(u);
      return { success: true };
    } catch (err) {
      setError(err.message);
      return { success: false, error: err.message };
    } finally {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (email, password) => {
    try {
      setError(null);
      setLoading(true);
      await authClient.login(email, password);
      const u = authClient.getStoredUser();
      setUser(u);
      return { success: true };
    } catch (err) {
      setError(err.message);
      return { success: false, error: err.message };
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await authClient.logout();
    setUser(null);
    setError(null);
  }, []);

  const updateUserProfile = useCallback(async (profileData) => {
    try {
      setError(null);
      const updatedUser = await authClient.updateProfile(profileData);
      setUser(updatedUser);
      return { success: true };
    } catch (err) {
      setError(err.message);
      return { success: false, error: err.message };
    }
  }, []);

  const value = useMemo(() => ({
    user,
    loading,
    error,
    isAuthenticated: !!user,
    register,
    login,
    logout,
    updateUserProfile,
  }), [user, loading, error, register, login, logout, updateUserProfile]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
