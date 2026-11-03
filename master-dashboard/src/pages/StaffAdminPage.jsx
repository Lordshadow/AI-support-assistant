import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

export const StaffAdminPage = ({ showToast }) => {
  const { staff } = useAuth();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchSessions = async () => {
    setLoading(true);
    try {
      const resp = await api.get('/api/admin/v1/auth/sessions');
      setSessions(resp.data || []);
    } catch (err) {
      showToast('error', 'Failed to fetch active staff sessions.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleRevoke = async (sessionId) => {
    try {
      await api.delete(`/api/admin/v1/auth/sessions/${sessionId}`);
      showToast('success', `Session ${sessionId.slice(0, 12)} revoked.`);
      fetchSessions();
    } catch (err) {
      showToast('error', 'Failed to revoke staff session.');
    }
  };

  if (staff?.role !== 'admin') {
    return (
      <div className="page-container">
        <div className="alert-error">
          Access Denied: The Staff Administration console is strictly restricted to Admin users.
        </div>
      </div>
    );
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2>Staff Identity &amp; Session Administration</h2>
          <p>
            Administer staff roles (`executive`, `manager`, `admin`), monitor active opaque sessions,
            and enforce immediate session revocation. Admins cannot approve refunds or view customer dialogue.
          </p>
        </div>
        <button onClick={fetchSessions} className="btn-secondary">
          🔄 Refresh
        </button>
      </div>

      <div className="admin-banner">
        <span className="banner-icon">🔒</span>
        <div>
          <strong>Separation of Duties (R3 / R5):</strong> Platform Administrators manage staff
          access, API credentials, and sessions, but are strictly prohibited from approving monetary
          refunds or browsing customer conversation dialogue.
        </div>
      </div>

      <div className="table-card">
        <div className="card-title p-4 border-b">Active Server-Side Staff Sessions (PostgreSQL)</div>
        {loading ? (
          <div className="loading-state">Loading active sessions...</div>
        ) : sessions.length === 0 ? (
          <div className="empty-state">No other active staff sessions found.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Session ID</th>
                <th>Staff ID</th>
                <th>Tenant</th>
                <th>Created At</th>
                <th>Expires At</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.session_id}>
                  <td>
                    <span className="font-mono text-xs">{s.session_id.slice(0, 16)}...</span>
                  </td>
                  <td>
                    <span className="font-bold">{s.staff_id}</span>
                  </td>
                  <td>
                    <span className="badge badge-neutral">{s.active_tenant_id}</span>
                  </td>
                  <td>
                    <span className="text-muted text-xs">{s.created_at?.slice(0, 16)}</span>
                  </td>
                  <td>
                    <span className="text-muted text-xs">{s.expires_at?.slice(0, 16)}</span>
                  </td>
                  <td>
                    <span className="status-pill status-active">Active</span>
                  </td>
                  <td>
                    <button
                      onClick={() => handleRevoke(s.session_id)}
                      className="btn-danger btn-sm"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
