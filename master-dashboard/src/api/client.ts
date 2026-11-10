import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const getStoredCsrf = () => {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage.getItem('novaretail_csrf') || '';
    }
  } catch {
    return '';
  }
  return '';
};

let currentCsrfToken = getStoredCsrf();

export const setCsrfToken = (token: string | null) => {
  currentCsrfToken = token || '';
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      if (token) {
        window.localStorage.setItem('novaretail_csrf', token);
      } else {
        window.localStorage.removeItem('novaretail_csrf');
      }
    }
  } catch {
    // Ignore storage quota or access errors
  }
};

export const getCsrfToken = () => currentCsrfToken;

export const api = axios.create({
  baseURL: '',
  withCredentials: true, // Secure HttpOnly session cookie
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Inject unique correlation ID for observability
    const correlationId = `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    config.headers['X-Correlation-ID'] = correlationId;

    // Attach CSRF token on state-mutating requests
    const method = (config.method || '').toLowerCase();
    if (['post', 'put', 'delete', 'patch'].includes(method)) {
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
    // Capture rotated CSRF token
    if (response.data && response.data.csrf_token) {
      setCsrfToken(response.data.csrf_token);
    }
    return response;
  },
  (error: AxiosError<{ detail?: any; correlation_id?: string }>) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;

    if (status === 401) {
      // Session expired or revoked
      window.dispatchEvent(new CustomEvent('novaretail:unauthorized'));
    } else if (status === 403 && typeof detail === 'object' && detail?.code === 'STEP_UP_REQUIRED') {
      // Step-up verification required
      window.dispatchEvent(new CustomEvent('novaretail:stepup_required', { detail }));
    }
    return Promise.reject(error);
  }
);
