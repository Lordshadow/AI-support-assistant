import React, { useState } from 'react';
import { useAuth } from './context/AuthContext';
import { Navbar } from './components/Navbar';
import { Sidebar } from './components/Sidebar';
import { StepUpModal } from './components/StepUpModal';
import { Toast } from './components/Toast';

import { LoginPage } from './pages/LoginPage';
import { RefundsPage } from './pages/RefundsPage';
import { ConversationsPage } from './pages/ConversationsPage';
import { EscalationsPage } from './pages/EscalationsPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { ReportsPage } from './pages/ReportsPage';
import { StaffAdminPage } from './pages/StaffAdminPage';

export const App = () => {
  const { isAuthenticated } = useAuth();
  const [activeTab, setActiveTab] = useState('refunds');
  const [toast, setToast] = useState(null);

  const showToast = (type, message) => {
    setToast({ type, message });
    setTimeout(() => {
      setToast(null);
    }, 4500);
  };

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  const renderActivePage = () => {
    switch (activeTab) {
      case 'refunds':
        return <RefundsPage showToast={showToast} />;
      case 'conversations':
        return <ConversationsPage showToast={showToast} />;
      case 'escalations':
        return <EscalationsPage showToast={showToast} />;
      case 'knowledge':
        return <KnowledgePage showToast={showToast} />;
      case 'reports':
        return <ReportsPage showToast={showToast} />;
      case 'staff-admin':
        return <StaffAdminPage showToast={showToast} />;
      default:
        return <RefundsPage showToast={showToast} />;
    }
  };

  return (
    <div className="app-container">
      <Navbar />
      <div className="main-layout">
        <Sidebar activeTab={activeTab} onSelectTab={setActiveTab} />
        <main className="content-area">
          {renderActivePage()}
        </main>
      </div>
      <StepUpModal />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
};

export default App;
