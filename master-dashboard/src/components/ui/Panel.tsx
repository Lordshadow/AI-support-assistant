import React from 'react';

export interface PanelProps extends React.HTMLAttributes<HTMLDivElement> {
  tier?: 'chrome' | 'panel' | 'light' | 'data';
  notchedLabel?: string;
  notchedIcon?: React.ReactNode;
  headerAction?: React.ReactNode;
  children: React.ReactNode;
}

export const Panel: React.FC<PanelProps> = ({
  tier = 'panel',
  notchedLabel,
  notchedIcon,
  headerAction,
  children,
  className = '',
  ...props
}) => {
  const tierClass = {
    chrome: 'glass-chrome',
    panel: 'glass-panel',
    light: 'glass-panel-light',
    data: 'glass-data',
  }[tier];

  return (
    <div
      className={`relative ${tierClass} ${notchedLabel ? 'notched-panel pt-8' : 'p-6'} ${className}`}
      {...props}
    >
      {notchedLabel && (
        <div className="notched-tab-pill">
          {notchedIcon && <span className="inline-flex shrink-0">{notchedIcon}</span>}
          <span>{notchedLabel}</span>
        </div>
      )}

      {headerAction && (
        <div className="absolute top-4 right-6 z-10">
          {headerAction}
        </div>
      )}

      {children}
    </div>
  );
};
