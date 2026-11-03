import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export const LoginPage = () => {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaStep, setMfaStep] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const res = await login(email, password, mfaStep ? mfaCode : null);
      if (res.mfaRequired) {
        setMfaStep(true);
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Authentication failed. Please verify your email and password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrapper">
      <div className="login-card">
        <div className="login-header">
          <div className="login-logo">NR</div>
          <h2>NovaRetail Control Console</h2>
          <p>Enterprise Customer Support Operations & Governance</p>
        </div>

        {error && <div className="alert-error">{error}</div>}

        <form onSubmit={handleSubmit} className="login-form">
          {!mfaStep ? (
            <>
              <div className="form-group">
                <label>Staff Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="executive@novaretail.com"
                  required
                  autoFocus
                />
              </div>

              <div className="form-group">
                <label>Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  required
                />
              </div>
            </>
          ) : (
            <div className="form-group">
              <label>TOTP MFA Authenticator Code</label>
              <p className="field-hint">
                Two-Factor Authentication is enabled on your staff account. Enter the 6-digit code from your authenticator app.
              </p>
              <input
                type="text"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="000000"
                maxLength={6}
                required
                autoFocus
                className="otp-field"
              />
            </div>
          )}

          <button type="submit" disabled={loading} className="login-submit-btn">
            {loading ? 'Authenticating...' : mfaStep ? 'Verify TOTP & Enter' : 'Sign In with SSO / Credentials'}
          </button>
        </form>

        <div className="login-footer">
          <span>Protected by Argon2id Password Hashing, RFC 6238 TOTP MFA & PostgreSQL RLS.</span>
        </div>
      </div>
    </div>
  );
};
