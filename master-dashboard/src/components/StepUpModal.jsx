import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export const StepUpModal = () => {
  const { stepUpOpen, setStepUpOpen, performStepUp } = useAuth();
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!stepUpOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!password) {
      setError('Staff password is required for step-up verification.');
      return;
    }
    setLoading(true);
    setError('');

    try {
      const ok = await performStepUp(password, mfaCode || null);
      if (!ok) {
        setError('Invalid password or TOTP MFA code. Please re-enter credentials.');
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Step-up verification failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-box">
        <div className="modal-header">
          <div className="modal-badge">SECURITY STEP-UP</div>
          <h3>High-Privilege Authorization Required</h3>
          <p>
            You are attempting an action that modifies financial policy, grants refunds &gt; ₹5,000,
            or accesses unmasked customer dialogue. Re-authenticate to proceed.
          </p>
        </div>

        {error && <div className="alert-error">{error}</div>}

        <form onSubmit={handleSubmit} className="modal-form">
          <div className="form-group">
            <label>Staff Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your current password"
              autoFocus
              required
            />
          </div>

          <div className="form-group">
            <label>TOTP MFA Authenticator Code (Optional)</label>
            <input
              type="text"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value)}
              placeholder="6-digit code if MFA enabled"
              maxLength={6}
            />
          </div>

          <div className="modal-actions">
            <button
              type="button"
              onClick={() => {
                setStepUpOpen(false);
                setError('');
              }}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button type="submit" disabled={loading} className="btn-primary">
              {loading ? 'Verifying...' : 'Authorize Action'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
