import React from 'react';
import { Inbox, CheckCircle2 } from 'lucide-react';
import { Button } from './Button';

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  variant?: 'cleared' | 'empty';
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  description,
  actionLabel,
  onAction,
  variant = 'empty',
  className = '',
}) => {
  const defaultIcon = variant === 'cleared' ? (
    <CheckCircle2 className="w-10 h-10 text-[#2ED573]" />
  ) : (
    <Inbox className="w-10 h-10 text-[#3FD2C0]" />
  );

  return (
    <div
      className={`glass-panel p-8 text-center flex flex-col items-center justify-center rounded-3xl border border-[rgba(63,210,192,0.18)] ${className}`}
    >
      <div className="w-16 h-16 rounded-2xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] flex items-center justify-center mb-4 shadow-[0_8px_24px_rgba(0,0,0,0.25)]">
        {icon || defaultIcon}
      </div>
      <h3 className="text-lg font-bold text-[#EAF6F4] mb-1">{title}</h3>
      <p className="text-sm text-[#B6D5D1] max-w-md mb-6 leading-relaxed">
        {description}
      </p>
      {actionLabel && onAction && (
        <Button variant="secondary" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
};
