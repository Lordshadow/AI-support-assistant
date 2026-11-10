import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Navbar } from './components/Navbar';
import { BottomStatusBar } from './components/BottomStatusBar';
import { StepUpModal } from './components/StepUpModal';
import { ProtectedRoute } from './components/ProtectedRoute';

import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { RefundsPage } from './pages/RefundsPage';
import { ConversationsPage } from './pages/ConversationsPage';
import { EscalationsPage } from './pages/EscalationsPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { SettingsPage } from './pages/SettingsPage';
import { ReportsPage } from './pages/ReportsPage';
import { StaffAdminPage } from './pages/StaffAdminPage';
import { ScriptsPage } from './pages/ScriptsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OrderLookupPage } from './pages/OrderLookupPage';

const AppShell: React.FC = () => {
  const { isAuthenticated } = useAuth();

  return (
    <div className="app-shell relative">
      {/* Procedural Nebula Mesh Background (Zero heavy raster assets) */}
      <div className="nebula-backdrop" aria-hidden="true">
        <div className="nebula-blob nebula-blob-1" />
        <div className="nebula-blob nebula-blob-2" />
        <div className="nebula-blob nebula-blob-3" />
        <div className="nebula-stars" />
      </div>

      {isAuthenticated && <Navbar />}

      <main className="main-content">
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          {/* Screen 1: Command Center Overview */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <OverviewPage />
              </ProtectedRoute>
            }
          />

          {/* Screen 2: Approval Queue */}
          <Route
            path="/refunds"
            element={
              <ProtectedRoute allowedRoles={['executive', 'manager', 'admin']}>
                <RefundsPage />
              </ProtectedRoute>
            }
          />

          {/* Screen 3: Conversation Viewer & Spec 14.1 Trace Drawer */}
          <Route
            path="/conversations"
            element={
              <ProtectedRoute allowedRoles={['executive', 'manager']}>
                <ConversationsPage />
              </ProtectedRoute>
            }
          />

          {/* Screen 4: Escalations Console */}
          <Route
            path="/escalations"
            element={
              <ProtectedRoute allowedRoles={['executive', 'manager', 'admin']}>
                <EscalationsPage />
              </ProtectedRoute>
            }
          />

          {/* Screen 5: Policy & Knowledge Management */}
          <Route
            path="/knowledge"
            element={
              <ProtectedRoute allowedRoles={['executive', 'manager', 'admin']}>
                <KnowledgePage />
              </ProtectedRoute>
            }
          />

          {/* Screen 6: Settings & Tenant Governance */}
          <Route
            path="/settings"
            element={
              <ProtectedRoute allowedRoles={['executive', 'manager', 'admin']}>
                <SettingsPage />
              </ProtectedRoute>
            }
          />

          {/* Screen 7: Operational Reports */}
          <Route
            path="/reports"
            element={
              <ProtectedRoute allowedRoles={['manager', 'admin']}>
                <ReportsPage />
              </ProtectedRoute>
            }
          />

          {/* Screen 8: Staff & Workspace Administration (Admin only) */}
          <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <StaffAdminPage />
              </ProtectedRoute>
            }
          />

          <Route path="/orders" element={<ProtectedRoute allowedRoles={['manager', 'admin']}><OrderLookupPage /></ProtectedRoute>} />

          {/* Operations & Developer Scripts Hub */}
          <Route
            path="/scripts"
            element={
              <ProtectedRoute allowedRoles={['executive', 'manager', 'admin']}>
                <ScriptsPage />
              </ProtectedRoute>
            }
          />

          {/* 404 Catch-All */}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>

      {isAuthenticated && <BottomStatusBar />}
      <StepUpModal />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
};

export default App;
