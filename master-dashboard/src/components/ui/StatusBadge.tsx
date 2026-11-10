import React from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, Clock } from 'lucide-react';

export interface StatusBadgeProps {
  status: 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'pending';
  label: string;
  size?: 'sm' | 'md';
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  size = 'md',
  className = '',
}) => {
  const configs = {
    success: {
      bg: 'rgba(46, 213, 115, 0.15)',
      border: 'rgba(46, 213, 115, 0.40)',
      text: '#2ED573',
      icon: CheckCircle2,
    },
    warning: {
      bg: 'rgba(255, 165, 2, 0.15)',
      border: 'rgba(255, 165, 2, 0.45)',
      text: '#FFA502',
      icon: AlertTriangle,
    },
    danger: {
      bg: 'rgba(255, 82, 82, 0.15)',
      border: 'rgba(255, 82, 82, 0.45)',
      text: '#FF5252',
      icon: AlertCircle,
    },
    info: {
      bg: 'rgba(63, 210, 192, 0.15)',
      border: 'rgba(63, 210, 192, 0.40)',
      text: '#3FD2C0',
      icon: Info,
    },
    pending: {
      bg: 'rgba(255, 165, 2, 0.12)',
      border: 'rgba(255, 165, 2, 0.35)',
      text: '#FFB830',
      icon: Clock,
    },
    neutral: {
      bg: 'rgba(182, 213, 209, 0.12)',
      border: 'rgba(182, 213, 209, 0.30)',
      text: '#B6D5D1',
      icon: Info,
    },
  }[status];

  const IconComponent = configs.icon;
  const padding = size === 'sm' ? 'px-2 py-0.5 text-[11px] gap-1' : 'px-3 py-1 text-xs gap-1.5';

  return (
    <span
      className={`inline-flex items-center font-medium rounded-full border ${padding} ${className}`}
      style={{
        backgroundColor: configs.bg,
        borderColor: configs.border,
        color: configs.text,
      }}
    >
      <IconComponent className={size === 'sm' ? 'w-3 h-3 shrink-0' : 'w-3.5 h-3.5 shrink-0'} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
};
