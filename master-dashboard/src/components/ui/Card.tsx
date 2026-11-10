import React from 'react';
import { ArrowUpRight } from 'lucide-react';
import { IconButton } from './Button';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'dark' | 'light' | 'opaque';
  microCaption?: string;
  title?: string;
  actionTitle?: string;
  onAction?: () => void;
  children: React.ReactNode;
}

export const Card: React.FC<CardProps> = ({
  variant = 'dark',
  microCaption,
  title,
  actionTitle,
  onAction,
  children,
  className = '',
  ...props
}) => {
  const variantClass = {
    dark: 'glass-panel text-[#EAF6F4]',
    light: 'glass-panel-light text-[#0F3D3B]',
    opaque: 'glass-data text-[#EAF6F4]',
  }[variant];

  return (
    <div
      className={`relative p-5 transition-all duration-200 border rounded-2xl ${variantClass} ${className}`}
      {...props}
    >
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          {microCaption && (
            <p className={variant === 'light' ? 'micro-label-light' : 'micro-label'}>
              {microCaption}
            </p>
          )}
          {title && (
            <h3 className={`text-base font-bold mt-0.5 ${variant === 'light' ? 'text-[#0F3D3B]' : 'text-[#EAF6F4]'}`}>
              {title}
            </h3>
          )}
        </div>

        {onAction && (
          <IconButton
            variant="square-arrow"
            size="sm"
            title={actionTitle || 'Open details'}
            onClick={onAction}
          >
            <ArrowUpRight className="w-4 h-4" />
          </IconButton>
        )}
      </div>

      <div>{children}</div>
    </div>
  );
};
