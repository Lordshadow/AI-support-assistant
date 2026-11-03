import React from 'react';
import { useAuth } from '../context/AuthContext';

export const Navbar = () => {
  const { staff, logout } = useAuth();

  if (!staff) return null;

  const roleBadgeColors = {
    executive: 'bg-blue-100 text-blue-800 border-blue-300',
    manager: 'bg-purple-100 text-purple-800 border-purple-300',
    admin: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  };

  return (
    <header className="navbar">
      <div className="navbar-brand">
        <div className="brand-logo">NR</div>
        <div className="brand-text">
          <span className="brand-title">NovaRetail</span>
          <span className="brand-subtitle">Master Control Dashboard</span>
        </div>
      </div>

      <div className="navbar-center">
        <div className="tenant-badge">
          <span className="tenant-dot"></span>
          <span className="tenant-label">Tenant:</span>
          <strong>{staff.tenantId || 'tenant_novaretail'}</strong>
        </div>
      </div>

      <div className="navbar-actions">
        {staff.isSteppedUp && (
          <span className="stepup-badge" title="High-privilege step-up authentication active (TTL: 5m)">
            🛡️ Stepped Up
          </span>
        )}

        <div className="user-profile">
          <div className="user-avatar">{staff.fullName ? staff.fullName[0].toUpperCase() : 'U'}</div>
          <div className="user-info">
            <span className="user-name">{staff.fullName}</span>
            <span className={`role-pill ${roleBadgeColors[staff.role] || 'bg-gray-100'}`}>
              {staff.role ? staff.role.toUpperCase() : 'STAFF'}
            </span>
          </div>
        </div>

        <button onClick={logout} className="logout-btn" title="Sign out of Master Control Dashboard">
          Sign Out
        </button>
      </div>
    </header>
  );
};
