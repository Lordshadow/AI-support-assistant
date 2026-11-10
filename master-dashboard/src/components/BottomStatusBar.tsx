import React from 'react';
import { Home, Layers } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const BottomStatusBar: React.FC = () => {
  const navigate = useNavigate();
  const { staff } = useAuth();

  if (!staff) return null;

  return (
    <div
      role="contentinfo"
      aria-label="System status bar"
      className="bottom-status-bar glass-chrome border border-[rgba(63,210,192,0.25)] shadow-[0_12px_40px_rgba(4,30,29,0.5)]"
    >
      {/* Left Status Label */}
      <div className="flex items-center gap-3">
        <span className="text-[11px] font-bold uppercase tracking-widest text-[#EAF6F4]">SUPPORT DESK</span>
      </div>

      {/* Center Circular Home Action Button */}
      <div className="absolute left-1/2 -translate-x-1/2 -top-3">
        <button
          onClick={() => navigate('/')}
          aria-label="Return to Overview command center"
          title="Overview Command Center"
          className="circular-home-btn shadow-[0_4px_16px_rgba(63,210,192,0.4)]"
        >
          <Home className="w-4 h-4" />
        </button>
      </div>

      {/* Right Metadata */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-[11px] text-[#B6D5D1]">
          <Layers className="w-3.5 h-3.5 text-[#3FD2C0]" />
          <span className="hidden md:inline font-mono">TENANT:</span>
          <span className="font-semibold text-[#EAF6F4]">{staff.tenantId}</span>
        </div>
      </div>
    </div>
  );
};
