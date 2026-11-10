import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api, setCsrfToken } from '../api/client';
import { StaffUser, StaffRole } from '../types/schemas';

interface AuthContextType {
  staff: StaffUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string, mfaCode?: string) => Promise<{ success?: boolean; mfaRequired?: boolean; error?: string }>;
  logout: () => Promise<void>;
  performStepUp: (password: string, mfaCode?: string) => Promise<boolean>;
  requireStepUpWithAction: (actionCallback: () => void) => void;
  stepUpOpen: boolean;
  setStepUpOpen: (open: boolean) => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [staff, setStaff] = useState<StaffUser | null>(() => {
    try {
      const saved = sessionStorage.getItem('novaretail_staff_meta');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [stepUpOpen, setStepUpOpen] = useState<boolean>(false);
  const [stepUpCallback, setStepUpCallback] = useState<(() => void) | null>(null);
  const [mfaTicket, setMfaTicket] = useState<string | null>(null);

  useEffect(() => {
    const handleUnauthorized = () => {
      setStaff(null);
      sessionStorage.removeItem('novaretail_staff_meta');
      setCsrfToken(null);
    };

    const handleStepUpRequired = () => {
      setStepUpOpen(true);
    };

    window.addEventListener('novaretail:unauthorized', handleUnauthorized);
    window.addEventListener('novaretail:stepup_required', handleStepUpRequired);

    return () => {
      window.removeEventListener('novaretail:unauthorized', handleUnauthorized);
      window.removeEventListener('novaretail:stepup_required', handleStepUpRequired);
    };
  }, []);

  const login = async (email: string, password: string, mfaCode?: string) => {
    setIsLoading(true);
    try {
      let resp;
      if (mfaCode && mfaTicket) {
        resp = await api.post('/api/admin/v1/auth/mfa/verify', {
          mfa_ticket: mfaTicket,
          code: mfaCode,
        });
        setMfaTicket(null);
      } else {
        resp = await api.post('/api/admin/v1/auth/login', { email, password });
      }

      if (resp.data.status === 'mfa_required') {
        setMfaTicket(resp.data.mfa_ticket);
        setIsLoading(false);
        return { mfaRequired: true };
      }

      const staffData: StaffUser = {
        staffId: resp.data.staff_id || 'staff_001',
        email: resp.data.email || email,
        fullName: resp.data.full_name || email.split('@')[0],
        role: (resp.data.role as StaffRole) || 'executive',
        tenantId: resp.data.tenant_id || 'tenant_novaretail',
        isSteppedUp: false,
      };

      setStaff(staffData);
      sessionStorage.setItem('novaretail_staff_meta', JSON.stringify(staffData));
      if (resp.data.csrf_token) {
        setCsrfToken(resp.data.csrf_token);
      }
      return { success: true };
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Authentication failed. Please verify credentials.';
      return { error: typeof msg === 'string' ? msg : 'Login error' };
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    try {
      await api.post('/api/admin/v1/auth/logout');
    } catch (e) {
      console.warn('Logout API failed, clearing local session state:', e);
    } finally {
      setStaff(null);
      sessionStorage.removeItem('novaretail_staff_meta');
      setCsrfToken(null);
    }
  };

  const performStepUp = async (password: string, mfaCode?: string) => {
    try {
      const resp = await api.post('/api/admin/v1/auth/step-up', {
        password,
        totp_code: mfaCode,
      });

      if (resp.data.status === 'stepped_up') {
        setStaff((prev) => {
          if (!prev) return null;
          const updated = { ...prev, isSteppedUp: true };
          sessionStorage.setItem('novaretail_staff_meta', JSON.stringify(updated));
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
    } catch (e) {
      return false;
    }
  };

  const requireStepUpWithAction = useCallback((actionCallback: () => void) => {
    if (staff?.isSteppedUp) {
      actionCallback();
    } else {
      setStepUpCallback(() => actionCallback);
      setStepUpOpen(true);
    }
  }, [staff?.isSteppedUp]);

  return (
    <AuthContext.Provider
      value={{
        staff,
        isAuthenticated: !!staff,
        isLoading,
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

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
