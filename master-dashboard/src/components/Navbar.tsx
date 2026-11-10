import React, { useState, useEffect } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { LogOut, ShieldCheck, Search, ChevronDown } from 'lucide-react';
import { GlobalSearchModal } from './GlobalSearchModal';

export const Navbar: React.FC = () => {
  const { staff, logout } = useAuth();
  const [searchOpen, setSearchOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (!staff) return null;

  const isAdmin = staff.role === 'admin';

  const primaryLinks = [
    { to: '/', label: 'Overview' },
    { to: '/refunds', label: 'Approvals' },
    ...(isAdmin ? [] : [{ to: '/conversations', label: 'Conversations' }]),
    { to: '/escalations', label: 'Escalations' },
    { to: '/knowledge', label: 'Knowledge' },
  ];
  const secondaryLinks = [
    { to: '/settings', label: 'Settings' },
    { to: '/reports', label: 'Reports' },
    { to: '/scripts', label: 'Scripts' },
    ...(isAdmin ? [{ to: '/admin', label: 'Staff Admin' }] : []),
  ];
  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded-full text-xs font-semibold tracking-wide transition-colors whitespace-nowrap cursor-pointer ${isActive ? 'bg-[#3FD2C0] text-[#062F2E] font-bold' : 'text-[#B6D5D1] hover:text-[#EAF6F4] hover:bg-[rgba(255,255,255,0.06)]'}`;

  return (
    <>
      <header className="sticky top-4 z-40 px-4 sm:px-6 w-full max-w-[1440px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
        {/* Left: Floating Top Nav Pill Container */}
        <nav
          aria-label="Main Navigation"
          className="glass-chrome flex items-center gap-1 sm:gap-2 px-3 py-1.5 rounded-full shadow-[0_8px_32px_rgba(4,30,29,0.4)] border border-[rgba(63,210,192,0.22)] overflow-x-auto max-w-full"
        >
          {/* Brand Logo Pill Chip */}
          <div
            onClick={() => navigate('/')}
            className="flex items-center gap-2 pl-2 pr-3 py-1 cursor-pointer select-none group"
            title="NovaRetail Support Desk"
          >
            <div className="w-7 h-7 rounded-full bg-[#3FD2C0] flex items-center justify-center font-black text-xs text-[#062F2E] shadow-[0_0_12px_rgba(63,210,192,0.5)]">
              NR
            </div>
            <span className="hidden md:inline font-bold text-xs tracking-wider uppercase text-[#EAF6F4] group-hover:text-[#3FD2C0] transition-colors">
              NovaRetail
            </span>
          </div>

          <div className="h-4 w-px bg-[rgba(63,210,192,0.25)] mx-1" aria-hidden="true" />

          {/* Nav Links */}
          {primaryLinks.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === '/'}
              className={navLinkClass}
            >
              {link.label}
            </NavLink>
          ))}
          <details className="relative">
            <summary className="list-none flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-semibold text-[#B6D5D1] hover:text-[#EAF6F4] hover:bg-[rgba(255,255,255,0.06)] cursor-pointer whitespace-nowrap">
              More <ChevronDown className="w-3 h-3" />
            </summary>
            <div className="absolute right-0 top-full mt-2 min-w-40 p-1.5 rounded-xl glass-data border border-[rgba(63,210,192,0.22)] shadow-xl flex flex-col gap-1 z-50">
              {secondaryLinks.map((link) => (
                <NavLink key={link.to} to={link.to} className={navLinkClass}
                  onClick={(event) => event.currentTarget.closest('details')?.removeAttribute('open')}>
                  {link.label}
                </NavLink>
              ))}
            </div>
          </details>
          <button type="button" aria-label="Search records" title="Search records (Ctrl+K)" onClick={() => setSearchOpen(true)}
            className="p-2 rounded-full text-[#B6D5D1] hover:text-[#EAF6F4] hover:bg-[rgba(255,255,255,0.06)]">
            <Search className="w-4 h-4" />
          </button>
        </nav>

        {/* Right Section: User Profile Chip */}
        <div className="flex items-center gap-2.5">
          {/* User Profile Pill Chip */}
          <div className="glass-chrome flex items-center gap-2.5 pl-1.5 pr-2 py-1.5 rounded-full border border-[rgba(63,210,192,0.22)] shadow-[0_8px_24px_rgba(4,30,29,0.3)]">
            <div className="w-7 h-7 rounded-full bg-[rgba(15,92,88,0.9)] border border-[#3FD2C0] flex items-center justify-center text-xs font-bold text-[#3FD2C0]">
              {staff.fullName ? staff.fullName[0].toUpperCase() : 'U'}
            </div>

            <div className="hidden md:flex flex-col text-left">
              <span className="text-xs font-bold text-[#EAF6F4] leading-tight">
                {staff.fullName}
              </span>
              <div className="flex items-center gap-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#3FD2C0]">
                  {staff.role}
                </span>
                {staff.isSteppedUp && (
                  <span
                    className="inline-flex items-center gap-0.5 text-[9px] text-[#FFA502] font-semibold"
                    title="Elevated Step-Up Session Active"
                  >
                    <ShieldCheck className="w-2.5 h-2.5" />
                    Elevated
                  </span>
                )}
              </div>
            </div>

            <button
              onClick={logout}
              title="Sign out of Support Desk"
              aria-label="Sign out"
              className="p-1.5 rounded-full hover:bg-[rgba(255,82,82,0.2)] text-[#84ABA6] hover:text-[#FF8585] transition-colors cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </header>

      {/* Global Search Dialog */}
      <GlobalSearchModal isOpen={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  );
};
