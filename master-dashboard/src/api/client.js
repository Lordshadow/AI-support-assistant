import axios from 'axios';

let currentCsrfToken = localStorage.getItem('novaretail_csrf') || '';

export const setCsrfToken = (token) => {
  currentCsrfToken = token || '';
  if (token) {
    localStorage.setItem('novaretail_csrf', token);
  } else {
    localStorage.removeItem('novaretail_csrf');
  }
};

export const getCsrfToken = () => currentCsrfToken;

export const api = axios.create({
  baseURL: '',
  withCredentials: true, // Send HttpOnly session cookie
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config) => {
    // Attach CSRF token on state-mutating HTTP methods
    if (['post', 'put', 'delete', 'patch'].includes((config.method || '').toLowerCase())) {
      if (currentCsrfToken) {
        config.headers['X-CSRF-Token'] = currentCsrfToken;
      }
    }
    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (response) => {
    // Capture CSRF token if returned in response body
    if (response.data && response.data.csrf_token) {
      setCsrfToken(response.data.csrf_token);
    }
    return response;
  },
  (error) => {
    const status = error.response ? error.response.status : null;
    const detail = error.response ? error.response.data?.detail : null;

    if (status === 401) {
      // Session expired or unauthenticated
      window.dispatchEvent(new CustomEvent('novaretail:unauthorized'));
    } else if (status === 403 && typeof detail === 'object' && detail?.code === 'STEP_UP_REQUIRED') {
      // Step-up verification required
      window.dispatchEvent(new CustomEvent('novaretail:stepup_required', { detail }));
    }
    return Promise.reject(error);
  }
);
