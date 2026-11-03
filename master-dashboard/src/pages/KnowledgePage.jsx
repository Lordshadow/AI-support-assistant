import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

export const KnowledgePage = ({ showToast }) => {
  const { staff, requireStepUpWithAction } = useAuth();
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadedClauses, setUploadedClauses] = useState(null);
  const [uploadLoading, setUploadLoading] = useState(false);

  // Confirmed policy values form
  const [returnWindowDays, setReturnWindowDays] = useState(30);
  const [excludedCategories, setExcludedCategories] = useState('digital, gift cards, perishables');
  const [autoRefundLimitInr, setAutoRefundLimitInr] = useState(2000);

  // Sync and eval state
  const [syncLoading, setSyncLoading] = useState(false);
  const [evalLoading, setEvalLoading] = useState(null);
  const [evalResult, setEvalResult] = useState({});
  const [overrideModal, setOverrideModal] = useState(null);
  const [overrideReason, setOverrideReason] = useState('');

  const isManagerOrAdmin = staff?.role === 'manager' || staff?.role === 'admin';

  const fetchVersions = async () => {
    setLoading(true);
    try {
      const resp = await api.get('/api/admin/v1/knowledge/versions');
      setVersions(resp.data || []);
    } catch (err) {
      showToast('error', 'Failed to load knowledge versions.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVersions();
  }, []);

  const handleFileUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile) {
      showToast('error', 'Please select a PDF, Markdown, or Text file to upload.');
      return;
    }

    setUploadLoading(true);
    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const resp = await api.post('/api/admin/v1/knowledge/policy/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setUploadedClauses(resp.data);
      showToast('success', `Policy parsed: ${resp.data.total_clauses} clauses extracted.`);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to upload and parse policy document.';
      showToast('error', typeof msg === 'string' ? msg : 'Error processing document.');
    } finally {
      setUploadLoading(false);
    }
  };

  const handleCreatePolicyDraft = async () => {
    if (!uploadedClauses || !uploadedClauses.clauses) return;

    try {
      const categoriesArray = excludedCategories
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);

      const payload = {
        filename: uploadedClauses.filename,
        clauses: uploadedClauses.clauses,
        confirmed_policy: {
          return_window_days: parseInt(returnWindowDays, 10),
          excluded_categories: categoriesArray,
          auto_refund_limit_inr: parseInt(autoRefundLimitInr, 10),
        },
      };

      const resp = await api.post('/api/admin/v1/knowledge/policy/draft', payload);
      showToast('success', `Draft policy version ${resp.data.version_id} created.`);
      setUploadedClauses(null);
      setSelectedFile(null);
      fetchVersions();
    } catch (err) {
      showToast('error', 'Failed to create policy draft.');
    }
  };

  const handleCatalogSync = async () => {
    setSyncLoading(true);
    try {
      const resp = await api.post('/api/admin/v1/knowledge/catalog/sync', {});
      if (resp.data.status === 'failed') {
        showToast('error', `Catalog sync aborted: ${resp.data.error_message}`);
      } else {
        showToast('success', 'Catalog sync completed with Deletion Guard safety checks.');
      }
      fetchVersions();
    } catch (err) {
      if (err.response?.status === 409) {
        showToast('error', '409 Conflict: An active catalog ingestion job is already running.');
      } else {
        showToast('error', 'Catalog sync failed.');
      }
    } finally {
      setSyncLoading(false);
    }
  };

  const handleRunEval = async (versionId) => {
    setEvalLoading(versionId);
    try {
      const resp = await api.post(`/api/admin/v1/knowledge/versions/${versionId}/eval`);
      setEvalResult({ ...evalResult, [versionId]: resp.data.eval_result });
      showToast('success', `Quality evaluation finished: Status is ${resp.data.eval_result.status}.`);
      fetchVersions();
    } catch (err) {
      showToast('error', 'Evaluation runner failed.');
    } finally {
      setEvalLoading(null);
    }
  };

  const handlePromote = async (version, override = false, reason = '') => {
    if (!isManagerOrAdmin) {
      showToast('error', 'Manager or Admin role required to promote knowledge versions.');
      return;
    }

    try {
      await api.post(`/api/admin/v1/knowledge/versions/${version.version_id}/promote`, {
        override,
        override_reason: reason || null,
      });
      showToast('success', `Version ${version.version_id} successfully promoted to active!`);
      setOverrideModal(null);
      setOverrideReason('');
      fetchVersions();
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 400 && !override) {
        // Offer manager override
        setOverrideModal(version);
      } else {
        showToast('error', typeof detail === 'string' ? detail : 'Promotion rejected by policy gate.');
      }
    }
  };

  const handleRollback = async (type) => {
    if (!isManagerOrAdmin) {
      showToast('error', 'Manager role required to execute one-click rollback.');
      return;
    }

    try {
      const resp = await api.post('/api/admin/v1/knowledge/rollback', {
        version_type: type,
      });
      showToast('success', `Rolled back to previous version ${resp.data.version_id}. Cache invalidated.`);
      fetchVersions();
    } catch (err) {
      showToast('error', 'Rollback failed: No previous archived version found.');
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2>Knowledge Staging, Ingestion &amp; Eval Gate</h2>
          <p>
            Immutable version manifests (`knowledge_versions`), safe PDF clause extraction,
            confirmed policy parameters, catalog deletion guards (&gt; 20% drop aborts), and
            automated quality eval benchmarks.
          </p>
        </div>
        <div className="header-actions">
          <button onClick={handleCatalogSync} disabled={syncLoading} className="btn-primary">
            {syncLoading ? 'Syncing Catalog...' : '📦 Sync Product Catalog'}
          </button>
          <button onClick={() => handleRollback('policy')} className="btn-secondary">
            ↩️ Rollback Policy
          </button>
        </div>
      </div>

      {/* Policy Upload Section */}
      <div className="knowledge-grid">
        <div className="panel-card">
          <div className="card-title">Upload Return Policy Document</div>
          <p className="card-desc">
            Upload store return policy in PDF (text layer), Markdown, or plain text. Unmapped glyphs
            or scanned PDFs (&gt; 30% unmapped characters) are automatically rejected.
          </p>

          <form onSubmit={handleFileUpload} className="upload-form">
            <input
              type="file"
              accept=".pdf,.md,.txt"
              onChange={(e) => setSelectedFile(e.target.files[0])}
              className="file-input"
            />
            <button type="submit" disabled={uploadLoading || !selectedFile} className="btn-primary">
              {uploadLoading ? 'Parsing Clauses...' : 'Upload & Parse Clauses'}
            </button>
          </form>

          {/* Clause Preview and Confirmed Values Form */}
          {uploadedClauses && (
            <div className="preview-section">
              <h4>Extracted Clause Preview ({uploadedClauses.total_clauses} Clauses)</h4>
              <div className="clause-preview-list">
                {uploadedClauses.clauses.map((c, i) => (
                  <div key={i} className="clause-preview-item">
                    <strong>{c.clause_id}: {c.title}</strong>
                    <div className="preview-snippet">{c.preview_snippet}</div>
                  </div>
                ))}
              </div>

              <div className="confirmed-form">
                <h4>Confirmed Policy Values Form</h4>
                <div className="form-row">
                  <div className="form-group">
                    <label>Return Window (Days)</label>
                    <input
                      type="number"
                      value={returnWindowDays}
                      onChange={(e) => setReturnWindowDays(e.target.value)}
                      min={1}
                      max={365}
                    />
                  </div>
                  <div className="form-group">
                    <label>Auto-Refund Ceiling (INR)</label>
                    <input
                      type="number"
                      value={autoRefundLimitInr}
                      onChange={(e) => setAutoRefundLimitInr(e.target.value)}
                      min={0}
                      max={50000}
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Excluded Categories (Comma-separated)</label>
                  <input
                    type="text"
                    value={excludedCategories}
                    onChange={(e) => setExcludedCategories(e.target.value)}
                  />
                </div>
                <button onClick={handleCreatePolicyDraft} className="btn-success">
                  Save Draft Policy Version
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Versions Table */}
        <div className="panel-card">
          <div className="card-title">Version Manifests &amp; Quality Gates</div>
          {loading ? (
            <div className="loading-state">Loading manifests...</div>
          ) : versions.length === 0 ? (
            <div className="empty-state">No knowledge versions created yet.</div>
          ) : (
            <div className="versions-list">
              {versions.map((v) => {
                const evalInfo = v.eval_result || evalResult[v.version_id];
                const isPassed = evalInfo?.status === 'passed';
                const isActive = v.status === 'active';
                const isDraft = v.status === 'draft';

                return (
                  <div key={v.version_id} className={`version-card version-${v.status}`}>
                    <div className="version-card-header">
                      <div>
                        <span className="font-mono font-bold">{v.version_id}</span>
                        <span className="badge badge-neutral ml-2">{v.type.toUpperCase()}</span>
                        <span className={`status-pill status-${v.status} ml-2`}>{v.status}</span>
                      </div>
                      <span className="text-muted text-xs">
                        Chunks: {v.chunk_count || 0} | {v.created_at?.slice(0, 16)}
                      </span>
                    </div>

                    {evalInfo && (
                      <div className="eval-status-box">
                        <span className={`eval-pill ${isPassed ? 'pill-pass' : 'pill-fail'}`}>
                          {isPassed ? 'EVAL PASSED' : 'EVAL FAILED'}
                        </span>
                        <span className="text-xs">
                          Deterministic: {(evalInfo.deterministic_score * 100).toFixed(0)}% (100% Req) | Fuzzy:{' '}
                          {(evalInfo.fuzzy_score * 100).toFixed(0)}% (&ge;90% Req)
                        </span>
                      </div>
                    )}

                    <div className="version-card-actions">
                      {isDraft && (
                        <button
                          onClick={() => handleRunEval(v.version_id)}
                          disabled={evalLoading === v.version_id}
                          className="btn-secondary btn-sm"
                        >
                          {evalLoading === v.version_id ? 'Evaluating...' : '🧪 Run Eval Gate'}
                        </button>
                      )}

                      {isDraft && (
                        <button
                          onClick={() => handlePromote(v, false)}
                          className="btn-primary btn-sm"
                        >
                          🚀 Promote to Active
                        </button>
                      )}

                      {isActive && <span className="active-indicator">⭐ Current Active Index</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Manager Override Modal */}
      {overrideModal && (
        <div className="modal-backdrop">
          <div className="modal-box">
            <div className="modal-header">
              <div className="modal-badge">QUALITY GATE BLOCKED</div>
              <h3>Manager Quality Eval Override</h3>
              <p>
                Version {overrideModal.version_id} failed automated quality benchmarks. As a Manager,
                you may apply an override with step-up verification and mandatory written justification.
              </p>
            </div>

            <div className="form-group">
              <label>Manager Override Justification Reason (Audited)</label>
              <textarea
                rows={3}
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                placeholder="Explain why this version is being promoted despite failing benchmark scores..."
                required
                autoFocus
              ></textarea>
            </div>

            <div className="modal-actions">
              <button onClick={() => setOverrideModal(null)} className="btn-secondary">
                Cancel
              </button>
              <button
                onClick={() => {
                  requireStepUpWithAction(() =>
                    handlePromote(overrideModal, true, overrideReason)
                  );
                }}
                className="btn-warning"
              >
                Step-Up &amp; Force Promote
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
