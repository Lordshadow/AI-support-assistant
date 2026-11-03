import React, { createContext, useContext, useState, useEffect } from 'react';
import { api, setCsrfToken } from '../api/client';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [staff, setStaff] = useState(() => {
    try {
      const saved = localStorage.getItem('novaretail_staff');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const [stepUpOpen, setStepUpOpen] = useState(false);
  const [stepUpCallback, setStepUpCallback] = useState(null);

  useEffect(() => {
    const handleUnauthorized = () => {
      setStaff(null);
      localStorage.removeItem('novaretail_staff');
      setCsrfToken('');
    };

    const handleStepUpRequired = (event) => {
      setStepUpOpen(true);
    };

    window.addEventListener('novaretail:unauthorized', handleUnauthorized);
    window.addEventListener('novaretail:stepup_required', handleStepUpRequired);

    return () => {
      window.removeEventListener('novaretail:unauthorized', handleUnauthorized);
      window.removeEventListener('novaretail:stepup_required', handleStepUpRequired);
    };
  }, []);

  const login = async (email, password, mfaCode = null) => {
    const resp = await api.post('/api/admin/v1/auth/login', {
      email,
      password,
      mfa_code: mfaCode,
    });

    if (resp.data.mfa_required) {
      return { mfaRequired: true, tempToken: resp.data.temp_token };
    }

    const staffData = {
      staffId: resp.data.staff_id,
      email: resp.data.email,
      fullName: resp.data.full_name,
      role: resp.data.role,
      tenantId: resp.data.tenant_id,
      isSteppedUp: false,
    };

    setStaff(staffData);
    localStorage.setItem('novaretail_staff', JSON.stringify(staffData));
    if (resp.data.csrf_token) {
      setCsrfToken(resp.data.csrf_token);
    }
    return { success: true };
  };

  const logout = async () => {
    try {
      await api.post('/api/admin/v1/auth/logout');
    } catch (e) {
      console.warn('Logout API failed, clearing local session:', e);
    } finally {
      setStaff(null);
      localStorage.removeItem('novaretail_staff');
      setCsrfToken('');
    }
  };

  const performStepUp = async (password, mfaCode = null) => {
    const resp = await api.post('/api/admin/v1/auth/step-up', {
      password,
      mfa_code: mfaCode,
    });

    if (resp.data.success) {
      setStaff((prev) => {
        const updated = { ...prev, isSteppedUp: true };
        localStorage.setItem('novaretail_staff', JSON.stringify(updated));
        return updated;
      });
      setStepUpOpen(false);
      if (stepUpCallback) {
        stepUpCallback();
        setStepUpCallback(null);
      }
      return true;
    }
    return false;
  };

  const requireStepUpWithAction = (actionCallback) => {
    if (staff?.isSteppedUp) {
      actionCallback();
    } else {
      setStepUpCallback(() => actionCallback);
      setStepUpOpen(true);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        staff,
        isAuthenticated: !!staff,
        login,
        logout,
        performStepUp,
        requireStepUpWithAction,
        stepUpOpen,
        setStepUpOpen,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
