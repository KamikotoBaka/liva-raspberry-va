// API Configuration for frontend
// In development, Vite proxy handles /api routes
// In production, we need to know the backend URL

const getApiBaseUrl = () => {
  // Check for environment variable (set at build time)
  if (import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL
  }

  // Check for runtime environment variable (set in window)
  if (typeof window !== 'undefined' && window.API_BASE_URL) {
    return window.API_BASE_URL
  }

  // Default: use same host but explicit port for backend
  // This works when backend is on :8000 and frontend on :5173
  if (typeof window !== 'undefined' && window.location.hostname) {
    const hostname = window.location.hostname
    
    // If we're on port 5173 (Vite dev), go to 8000 (backend)
    if (window.location.port === '5173') {
      return `http://${hostname}:8000`
    }
    
    // In production, use the api subdomain next to the current host.
    if (hostname.startsWith('api.')) {
      return `${window.location.protocol}//${hostname}`
    }

    // livapi.local -> api.livapi.local
    if (window.location.port === '80' || window.location.port === '443' || !window.location.port) {
      return `${window.location.protocol}//api.${hostname}`
    }
    
    return `${window.location.protocol}//api.${hostname}`
  }

  // Fallback
  return 'http://localhost:8000'
}

export const API_BASE_URL = getApiBaseUrl()

/**
 * Helper to build full API endpoint URL
 * Reads runtime-injected window.API_BASE_URL on every call for production support
 * @param {string} path - API path (e.g., '/api/chat/turn')
 * @returns {string} - Full URL
 */
export const apiUrl = (path) => {
  // Always check for runtime-injected API URL first (set by frontend startup script)
  const baseUrl = (typeof window !== 'undefined' && window.API_BASE_URL) 
    ? window.API_BASE_URL 
    : API_BASE_URL
  
  if (!path.startsWith('/')) {
    path = '/' + path
  }
  
  // If baseUrl doesn't include /api, append it
  if (!baseUrl.includes('/api') && !path.startsWith('/api')) {
    return `${baseUrl}/api${path}`
  }
  
  return `${baseUrl}${path}`
}

// For convenience: fetch wrapper that uses correct API URL
export const apiFetch = (path, options = {}) => {
  return fetch(apiUrl(path), options)
}
