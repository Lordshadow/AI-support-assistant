import React from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react';

export interface ToastMessage {
  id?: string;
  type: 'success' | 'warning' | 'error' | 'info';
  message: string;
}

export interface ToastProps {
  toast: ToastMessage | null;
  onClose: () => void;
}

export const Toast: React.FC<ToastProps> = ({ toast, onClose }) => {
  if (!toast) return null;

  const isAssertive = toast.type === 'error' || toast.type === 'warning';

  const configs = {
    success: {
      border: '#2ED573',
      text: '#2ED573',
      bg: 'rgba(6, 47, 46, 0.95)',
      icon: CheckCircle2,
    },
    warning: {
      border: '#FFA502',
      text: '#FFA502',
      bg: 'rgba(6, 47, 46, 0.95)',
      icon: AlertTriangle,
    },
    error: {
      border: '#FF5252',
      text: '#FF5252',
      bg: 'rgba(6, 47, 46, 0.95)',
      icon: AlertCircle,
    },
    info: {
      border: '#3FD2C0',
      text: '#3FD2C0',
      bg: 'rgba(6, 47, 46, 0.95)',
      icon: Info,
    },
  }[toast.type];

  const IconComponent = configs.icon;

  return (
    <div
      aria-live={isAssertive ? 'assertive' : 'polite'}
      className="fixed bottom-20 right-6 z-50 max-w-md w-full animate-in fade-in slide-in-from-bottom-5 duration-200"
    >
      <div
        className="glass-data flex items-center justify-between gap-3 px-4 py-3 rounded-2xl shadow-[0_16px_36px_rgba(0,0,0,0.5)] border"
        style={{
          borderColor: configs.border,
          backgroundColor: configs.bg,
        }}
      >
        <div className="flex items-center gap-3">
          <IconComponent className="w-5 h-5 shrink-0" style={{ color: configs.text }} aria-hidden="true" />
          <span className="text-sm font-medium text-[#EAF6F4]">{toast.message}</span>
        </div>
        <button
          onClick={onClose}
          aria-label="Close notification"
          className="text-[#84ABA6] hover:text-[#EAF6F4] p-1 rounded-full hover:bg-[rgba(255,255,255,0.08)] transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
