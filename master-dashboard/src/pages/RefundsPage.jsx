import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

export const RefundsPage = ({ showToast }) => {
  const { staff, requireStepUpWithAction } = useAuth();
  const [refunds, setRefunds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);
  const [staffNote, setStaffNote] = useState({});

  const fetchRefunds = async () => {
    setLoading(true);
    try {
      // In dashboard API, refund approvals queue is available via /api/admin/v1/refunds or support desk endpoint
      const resp = await api.get('/desk/refunds/pending');
      setRefunds(resp.data || []);
    } catch (err) {
      showToast('error', 'Failed to fetch pending refunds queue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRefunds();
  }, []);

  const handleApprove = (refund) => {
    // If refund > ₹5,000, require Step-Up authentication
    if (refund.amount_inr > 5000) {
      requireStepUpWithAction(() => executeDecision(refund.refund_id, 'approved'));
    } else {
      executeDecision(refund.refund_id, 'approved');
    }
  };

  const handleReject = (refund) => {
    executeDecision(refund.refund_id, 'rejected');
  };

  const executeDecision = async (refundId, decision) => {
    setActionLoading(refundId);
    try {
      const note = staffNote[refundId] || '';
      const resp = await api.post(`/desk/refunds/${refundId}/approve`, {
        staff_id: staff.staffId,
        decision: decision,
        notes: note,
      });

      if (resp.data.success) {
        showToast('success', `Refund ${refundId} successfully ${decision}.`);
        setRefunds((prev) => prev.filter((r) => r.refund_id !== refundId));
      } else {
        showToast('error', resp.data.message || 'Action failed.');
      }
    } catch (err) {
      if (err.response?.status === 409) {
        showToast('error', 'Conflict: This refund was already decided by another supervisor.');
        setRefunds((prev) => prev.filter((r) => r.refund_id !== refundId));
      } else {
        const msg = err.response?.data?.detail || 'Failed to process refund decision.';
        showToast('error', typeof msg === 'string' ? msg : 'Error processing decision.');
      }
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2>Refund Approvals Queue</h2>
          <p>
            Supervisor review queue for refund requests exceeding the auto-refund limit (&gt; ₹2,000).
            Requests &gt; ₹5,000 strictly require step-up re-authentication.
          </p>
        </div>
        <button onClick={fetchRefunds} disabled={loading} className="btn-secondary">
          {loading ? 'Refreshing...' : '🔄 Refresh Queue'}
        </button>
      </div>

      {loading ? (
        <div className="loading-state">Loading pending refunds...</div>
      ) : refunds.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">✅</div>
          <h3>Queue Cleared</h3>
          <p>There are no pending refund requests requiring supervisor approval at this time.</p>
        </div>
      ) : (
        <div className="table-card">
          <table className="data-table">
            <thead>
              <tr>
                <th>Refund ID</th>
                <th>Order Ref</th>
                <th>Customer ID</th>
                <th>Amount (INR)</th>
                <th>Reason</th>
                <th>Created At</th>
                <th>Supervisor Note</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {refunds.map((r) => {
                const isHighValue = r.amount_inr > 5000;
                return (
                  <tr key={r.refund_id}>
                    <td>
                      <span className="font-mono font-bold">{r.refund_id}</span>
                    </td>
                    <td>
                      <span className="badge badge-neutral">{r.order_id}</span>
                    </td>
                    <td>
                      <span className="text-muted">{r.customer_id}</span>
                    </td>
                    <td>
                      <span className={`amount-tag ${isHighValue ? 'high-value' : ''}`}>
                        ₹{r.amount_inr?.toLocaleString('en-IN')}
                        {isHighValue && <span className="stepup-tag">Step-Up</span>}
                      </span>
                    </td>
                    <td>
                      <div className="reason-text">{r.reason}</div>
                    </td>
                    <td>
                      <span className="text-muted text-xs">{r.created_at}</span>
                    </td>
                    <td>
                      <input
                        type="text"
                        placeholder="Add review note..."
                        value={staffNote[r.refund_id] || ''}
                        onChange={(e) =>
                          setStaffNote({ ...staffNote, [r.refund_id]: e.target.value })
                        }
                        className="table-input"
                      />
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button
                          onClick={() => handleApprove(r)}
                          disabled={actionLoading === r.refund_id}
                          className="btn-approve"
                        >
                          {actionLoading === r.refund_id ? 'Processing...' : 'Approve'}
                        </button>
                        <button
                          onClick={() => handleReject(r)}
                          disabled={actionLoading === r.refund_id}
                          className="btn-reject"
                        >
                          Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
