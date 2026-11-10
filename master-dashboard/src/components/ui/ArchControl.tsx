import React from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

export interface ArchControlProps {
  direction?: 'down' | 'up';
  label?: string;
  onClick: () => void;
  className?: string;
}

export const ArchControl: React.FC<ArchControlProps> = ({
  direction = 'down',
  label = 'JUMP',
  onClick,
  className = '',
}) => {
  const Icon = direction === 'down' ? ChevronDown : ChevronUp;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`arch-jump-control group ${className}`}
      aria-label={`${label} (${direction === 'down' ? 'Scroll down' : 'Back to top'})`}
    >
      <span className="text-[9px] font-bold tracking-widest text-[#3FD2C0] uppercase mb-0.5">
        {label}
      </span>
      <Icon className="w-3.5 h-3.5 text-[#3FD2C0] transition-transform duration-150 group-hover:scale-125" />
    </button>
  );
};
