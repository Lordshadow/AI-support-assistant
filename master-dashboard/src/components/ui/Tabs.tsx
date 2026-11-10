import React from 'react';

export interface TabItem {
  id: string;
  label: string;
  count?: number;
  icon?: React.ReactNode;
}

export interface TabsProps {
  tabs: TabItem[];
  activeTab: string;
  onChange: (id: string) => void;
  className?: string;
  size?: 'sm' | 'md';
}

export const Tabs: React.FC<TabsProps> = ({
  tabs,
  activeTab,
  onChange,
  className = '',
  size = 'md',
}) => {
  const padding = size === 'sm' ? 'px-3 py-1 text-xs' : 'px-4 py-2 text-sm';

  return (
    <div
      role="tablist"
      className={`inline-flex items-center gap-1.5 p-1.5 rounded-full bg-[rgba(6,47,46,0.8)] border border-[rgba(63,210,192,0.18)] ${className}`}
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={`inline-flex items-center gap-2 rounded-full font-semibold transition-all duration-150 cursor-pointer ${padding} ${
              isActive
                ? 'bg-[#3FD2C0] text-[#062F2E] shadow-[0_2px_12px_rgba(63,210,192,0.35)] font-bold'
                : 'text-[#B6D5D1] hover:text-[#EAF6F4] hover:bg-[rgba(255,255,255,0.06)]'
            }`}
          >
            {tab.icon && <span className="inline-flex shrink-0">{tab.icon}</span>}
            <span>{tab.label}</span>
            {typeof tab.count === 'number' && (
              <span
                className={`text-[11px] px-1.5 py-0.2 rounded-full font-mono ${
                  isActive
                    ? 'bg-[#062F2E] text-[#3FD2C0]'
                    : 'bg-[rgba(11,74,71,0.6)] text-[#B6D5D1]'
                }`}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};
