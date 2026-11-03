import React from 'react';
import { useAuth } from '../context/AuthContext';

export const Sidebar = ({ activeTab, onSelectTab }) => {
  const { staff } = useAuth();
  if (!staff) return null;

  const isAdmin = staff.role === 'admin';

  const menuItems = [
    {
      id: 'refunds',
      label: 'Refund Approvals',
      icon: '💳',
      desc: 'Atomic approval queue & money rules',
    },
    {
      id: 'conversations',
      label: 'Conversations & Traces',
      icon: '💬',
      desc: 'DPDP masked dialogue & Spec 14.1 trace',
    },
    {
      id: 'escalations',
      label: 'Escalations Queue',
      icon: '🚨',
      desc: 'Human takeover & bot silencing gate',
    },
    {
      id: 'knowledge',
      label: 'Knowledge & Policies',
      icon: '📚',
      desc: 'Manifests, clause preview & eval gate',
    },
    {
      id: 'reports',
      label: 'R4 Spend & Deflection',
      icon: '📊',
      desc: 'Token meters, daily ₹2,500 caps & KPIs',
    },
  ];

  if (isAdmin) {
    menuItems.push({
      id: 'staff-admin',
      label: 'Staff Administration',
      icon: '⚙️',
      desc: 'RBAC accounts & session revocation',
    });
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-section-title">CONTROL OPERATIONS</div>
      <nav className="sidebar-nav">
        {menuItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id)}
              className={`nav-item ${isActive ? 'active' : ''}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <div className="nav-content">
                <span className="nav-label">{item.label}</span>
                <span className="nav-desc">{item.desc}</span>
              </div>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <div className="sys-status">
          <span className="status-indicator"></span>
          <span>Gateway: Connected</span>
        </div>
        <div className="sys-version">v4.0 Production Build</div>
      </div>
    </aside>
  );
};
