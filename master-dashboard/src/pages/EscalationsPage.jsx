import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

export const EscalationsPage = ({ showToast }) => {
  const { staff } = useAuth();
  const [escalations, setEscalations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [resolvingId, setResolvingId] = useState(null);
  const [resolutionNote, setResolutionNote] = useState('');
  const [actionLoading, setActionLoading] = useState(null);

  const fetchEscalations = async () => {
    setLoading(true);
    try {
      const resp = await api.get('/api/admin/v1/escalations');
      setEscalations(resp.data || []);
    } catch (err) {
      showToast('error', 'Failed to fetch escalations queue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEscalations();
    const interval = setInterval(fetchEscalations, 15000); // Polling every 15s
    return () => clearInterval(interval);
  }, []);

  const handleClaim = async (escId) => {
    setActionLoading(escId);
    try {
      const resp = await api.post(`/api/admin/v1/escalations/${escId}/claim`);
      showToast('success', `Ticket ${escId} claimed. Bot is silenced for this customer.`);
      fetchEscalations();
    } catch (err) {
      if (err.response?.status === 409) {
        showToast('error', '409 Conflict: Another supervisor has already claimed this escalation ticket.');
        fetchEscalations();
      } else {
        showToast('error', 'Failed to claim escalation ticket.');
      }
    } finally {
      setActionLoading(null);
    }
  };

  const handleResolve = async (escId) => {
    if (!resolutionNote.trim()) {
      showToast('error', 'A resolution note is strictly required before closing a ticket.');
      return;
    }

    setActionLoading(escId);
    try {
      await api.post(`/api/admin/v1/escalations/${escId}/resolve`, {
        resolution_note: resolutionNote.trim(),
      });
      showToast('success', `Escalation ticket ${escId} marked resolved.`);
      setResolvingId(null);
      setResolutionNote('');
      fetchEscalations();
    } catch (err) {
      showToast('error', 'Failed to resolve escalation.');
    } finally {
      setActionLoading(null);
    }
  };

  const priorityStyles = {
    high: 'badge-danger',
    medium: 'badge-warning',
    low: 'badge-neutral',
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2>Escalations &amp; Human Takeover Console</h2>
          <p>
            Customer requests escalated to human care. While a ticket is open or assigned, the AI
            assistant is silenced with a fixed support notice.
          </p>
        </div>
        <button onClick={fetchEscalations} className="btn-secondary">
          🔄 Refresh
        </button>
      </div>

      <div className="silence-banner">
        <span className="banner-icon">🔇</span>
        <div>
          <strong>Bot Silencing Gate Active:</strong> When an escalation is assigned to an
          executive, AI model execution is completely bypassed to prevent conflicting messages.
        </div>
      </div>

      {loading ? (
        <div className="loading-state">Loading escalation tickets...</div>
      ) : escalations.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">🎉</div>
          <h3>Zero Backlog</h3>
          <p>All human escalation tickets have been claimed and resolved.</p>
        </div>
      ) : (
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>Ticket ID</th>
                <th>Conversation</th>
                <th>Priority</th>
                <th>Wait Time</th>
                <th>Status</th>
                <th>Assigned To</th>
                <th>Escalation Reason</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {escalations.map((e) => {
                const isAssignedToMe = e.assigned_to === staff?.staffId;
                const isOpen = e.state === 'open';

                return (
                  <tr key={e.esc_id}>
                    <td>
                      <span className="font-mono font-bold">{e.esc_id}</span>
                    </td>
                    <td>
                      <span className="badge badge-neutral">{e.conv_id}</span>
                    </td>
                    <td>
                      <span className={`badge ${priorityStyles[e.priority] || 'badge-neutral'}`}>
                        {e.priority.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      <span className="font-semibold text-danger">{e.wait_time_minutes} min</span>
                    </td>
                    <td>
                      <span className={`status-pill status-${e.state}`}>{e.state}</span>
                    </td>
                    <td>
                      <span className="text-muted text-xs">{e.assigned_to || 'Unassigned'}</span>
                    </td>
                    <td>
                      <div className="reason-text">{e.reason}</div>
                    </td>
                    <td>
                      {isOpen ? (
                        <button
                          onClick={() => handleClaim(e.esc_id)}
                          disabled={actionLoading === e.esc_id}
                          className="btn-claim"
                        >
                          {actionLoading === e.esc_id ? 'Claiming...' : 'Claim Ticket'}
                        </button>
                      ) : isAssignedToMe && e.state === 'assigned' ? (
                        <button
                          onClick={() => setResolvingId(e.esc_id)}
                          className="btn-resolve"
                        >
                          Resolve...
                        </button>
                      ) : (
                        <span className="text-muted text-xs">Handling</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Resolution Modal */}
      {resolvingId && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <h3>Resolve Ticket: {resolvingId}</h3>
              <p>Please document the resolution outcome before closing this support takeover.</p>
            </div>

            <div className="form-group">
              <label>Resolution Summary &amp; Notes (Mandatory)</label>
              <textarea
                rows={4}
                value={resolutionNote}
                onChange={(e) => setResolutionNote(e.target.value)}
                placeholder="Details of actions taken (e.g. issued replacement item, refunded shipping charges, clarified return address)..."
                required
                autoFocus
              ></textarea>
            </div>

            <div className="modal-actions">
              <button
                onClick={() => {
                  setResolvingId(null);
                  setResolutionNote('');
                }}
                className="btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={() => handleResolve(resolvingId)}
                disabled={actionLoading === resolvingId}
                className="btn-primary"
              >
                {actionLoading === resolvingId ? 'Resolving...' : 'Complete Resolution'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
