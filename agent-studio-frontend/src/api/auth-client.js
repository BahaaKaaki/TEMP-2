/**
 * Authentication API client
 *
 * Access tokens are held in memory only (never persisted to localStorage).
 * Refresh tokens are managed as HttpOnly cookies by the backend.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

const USER_KEY = 'agent_studio_user';

let _accessToken = null;
let _refreshPromise = null;

/**
 * Register a new user account.
 * The backend sets the refresh token as an HttpOnly cookie.
 */
export async function register(userData) {
  const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(userData),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Registration failed');
  }

  const data = await response.json();
  _accessToken = data.access_token;

  const user = await getMe();
  setUser(user);

  return data;
}

/**
 * Login with email and password.
 */
export async function login(email, password) {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Login failed');
  }

  const data = await response.json();
  _accessToken = data.access_token;

  const user = await getMe();
  setUser(user);

  return data;
}

/**
 * Refresh the access token via the HttpOnly refresh cookie.
 * The backend rotates the cookie automatically.
 *
 * Uses a singleton promise so concurrent callers share one in-flight
 * request instead of racing and revoking each other's cookies.
 */
export async function refreshAccessToken() {
  if (_refreshPromise) return _refreshPromise;

  _refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        clearAuth();
        throw new Error('Session expired. Please login again.');
      }

      const data = await response.json();
      _accessToken = data.access_token;
      return data;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

/**
 * Exchange a one-time OAuth authorization code for tokens.
 */
export async function exchangeOAuthCode(code) {
  const response = await fetch(`${API_BASE_URL}/api/auth/exchange-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ code }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'OAuth code exchange failed');
  }

  const data = await response.json();
  _accessToken = data.access_token;
  return data;
}

/**
 * Get current user profile.
 */
export async function getMe() {
  const accessToken = getAccessToken();
  if (!accessToken) {
    throw new Error('Not authenticated');
  }

  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    method: 'GET',
    headers: { 'Authorization': `Bearer ${accessToken}` },
    credentials: 'include',
  });

  if (!response.ok) {
    if (response.status === 401) {
      await refreshAccessToken();
      return getMe();
    }
    throw new Error('Failed to get user profile');
  }

  const user = await response.json();
  setUser(user);
  return user;
}

/**
 * Update user profile.
 */
export async function updateProfile(profileData) {
  const accessToken = getAccessToken();
  if (!accessToken) throw new Error('Not authenticated');

  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    method: 'PATCH',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(profileData),
  });

  if (!response.ok) {
    if (response.status === 401) {
      await refreshAccessToken();
      return updateProfile(profileData);
    }
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to update profile');
  }

  const user = await response.json();
  setUser(user);
  return user;
}

/**
 * Change user password.
 */
export async function changePassword(currentPassword, newPassword) {
  const accessToken = getAccessToken();
  if (!accessToken) throw new Error('Not authenticated');

  const response = await fetch(`${API_BASE_URL}/api/auth/change-password`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });

  if (!response.ok) {
    if (response.status === 401) {
      await refreshAccessToken();
      return changePassword(currentPassword, newPassword);
    }
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || 'Failed to change password');
  }
}

/**
 * Logout — tells the backend to revoke the refresh token and clears the cookie.
 */
export async function logout() {
  try {
    await fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    });
  } catch {
    // best-effort
  }
  clearAuth();
}

// ============================================================================
// Token & User helpers
// ============================================================================

export function setAccessToken(token) {
  _accessToken = token;
}

export function getAccessToken() {
  return _accessToken;
}

function setUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser() {
  const userJson = localStorage.getItem(USER_KEY);
  if (!userJson) return null;
  try {
    return JSON.parse(userJson);
  } catch {
    return null;
  }
}

export function clearAuth() {
  _accessToken = null;
  localStorage.removeItem(USER_KEY);
}

export function isAuthenticated() {
  return !!_accessToken;
}
