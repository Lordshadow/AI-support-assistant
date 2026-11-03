import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

export const ConversationsPage = ({ showToast }) => {
  const { staff, requireStepUpWithAction } = useAuth();
  const [conversations, setConversations] = useState([]);
  const [selectedConv, setSelectedConv] = useState(null);
  const [turns, setTurns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [turnsLoading, setTurnsLoading] = useState(false);
  const [selectedTrace, setSelectedTrace] = useState(null);
  const [isUnmasked, setIsUnmasked] = useState(false);

  const isManagerOrAdmin = staff?.role === 'manager' || staff?.role === 'admin';

  const fetchConversations = async () => {
    setLoading(true);
    try {
      const resp = await api.get('/api/admin/v1/conversations');
      setConversations(resp.data || []);
      if (resp.data?.length > 0 && !selectedConv) {
        selectConversation(resp.data[0]);
      }
    } catch (err) {
      showToast('error', 'Failed to load conversations.');
    } finally {
      setLoading(false);
    }
  };

  const selectConversation = async (conv) => {
    setSelectedConv(conv);
    setIsUnmasked(false);
    setTurnsLoading(true);
    try {
      const resp = await api.get(`/api/admin/v1/conversations/${conv.conv_id}`);
      setTurns(resp.data?.turns || []);
    } catch (err) {
      showToast('error', `Failed to load turns for ${conv.conv_id}`);
    } finally {
      setTurnsLoading(false);
    }
  };

  const handleUnmask = () => {
    if (!isManagerOrAdmin) {
      showToast('error', 'Forbidden: Manager role required to unmask customer PII dialogue.');
      return;
    }

    requireStepUpWithAction(async () => {
      try {
        const resp = await api.post(`/api/admin/v1/conversations/${selectedConv.conv_id}/unmask`);
        setTurns(resp.data?.turns || []);
        setIsUnmasked(true);
        showToast('success', 'PII Dialogue successfully unmasked. Audited in tamper-evident logs.');
      } catch (err) {
        showToast('error', 'Failed to unmask conversation dialogue.');
      }
    });
  };

  const viewTrace = async (turn) => {
    try {
      const resp = await api.get(
        `/api/admin/v1/conversations/${selectedConv.conv_id}/turns/${turn.turn_id}/trace`
      );
      setSelectedTrace(resp.data);
    } catch (err) {
      showToast('error', 'Failed to load Spec 14.1 turn trace.');
    }
  };

  useEffect(() => {
    fetchConversations();
  }, []);

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h2>Conversations &amp; Spec 14.1 Trace Viewer</h2>
          <p>
            DPDP-compliant dialogue auditing. Customer PII is scrubbed by default. Managers can
            perform step-up unmasking with full tamper-evident audit logging.
          </p>
        </div>
        <button onClick={fetchConversations} className="btn-secondary">
          🔄 Refresh
        </button>
      </div>

      <div className="conv-split-layout">
        {/* Left Column: Conversations List */}
        <div className="conv-sidebar-card">
          <div className="card-title">Session List</div>
          {loading ? (
            <div className="loading-state">Loading sessions...</div>
          ) : (
            <div className="conv-list">
              {conversations.map((c) => {
                const active = selectedConv?.conv_id === c.conv_id;
                return (
                  <div
                    key={c.conv_id}
                    onClick={() => selectConversation(c)}
                    className={`conv-list-item ${active ? 'active' : ''}`}
                  >
                    <div className="conv-item-header">
                      <span className="font-mono font-bold">{c.conv_id}</span>
                      <span className="badge badge-sm">{c.channel}</span>
                    </div>
                    <div className="conv-item-meta">
                      <span>Customer: {c.customer_id || 'Guest'}</span>
                      <span>{c.created_at?.slice(0, 16)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Dialogue & Traces */}
        <div className="conv-main-card">
          {selectedConv ? (
            <>
              <div className="conv-main-header">
                <div>
                  <h3>Session: {selectedConv.conv_id}</h3>
                  <div className="text-xs text-muted">
                    Channel: {selectedConv.channel} | Customer: {selectedConv.customer_id}
                  </div>
                </div>

                <div className="header-actions">
                  {isManagerOrAdmin && !isUnmasked && (
                    <button onClick={handleUnmask} className="btn-warning">
                      🔓 Manager Step-Up Unmask
                    </button>
                  )}
                  {isUnmasked && <span className="unmasked-badge">⚠️ Raw Dialogue Unmasked</span>}
                </div>
              </div>

              {turnsLoading ? (
                <div className="loading-state">Loading transcript turns...</div>
              ) : turns.length === 0 ? (
                <div className="empty-state">No messages recorded in this conversation.</div>
              ) : (
                <div className="transcript-flow">
                  {turns.map((t, idx) => (
                    <div key={t.turn_id || idx} className="turn-block">
                      <div className="turn-header">
                        <span className="turn-step">Step {t.step_index || idx + 1}</span>
                        <div className="turn-badges">
                          {t.intent && <span className="badge badge-info">{t.intent}</span>}
                          {t.latency_ms && <span className="badge badge-neutral">{t.latency_ms}ms</span>}
                          {t.grounding_score !== undefined && (
                            <span className="badge badge-success">
                              Grounding: {(t.grounding_score * 100).toFixed(0)}%
                            </span>
                          )}
                        </div>
                        <button onClick={() => viewTrace(t)} className="btn-trace-link">
                          🔍 View Spec 14.1 Trace
                        </button>
                      </div>

                      <div className="message-user">
                        <strong>Customer:</strong>
                        <div className="msg-text">{t.user_input_masked || t.user_input_raw}</div>
                      </div>

                      <div className="message-assistant">
                        <strong>Assistant:</strong>
                        <div className="msg-text">{t.assistant_response_masked || t.assistant_response_raw}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">Select a conversation to view transcript.</div>
          )}
        </div>
      </div>

      {/* Spec 14.1 Turn Trace Modal */}
      {selectedTrace && (
        <div className="modal-backdrop">
          <div className="modal-box modal-wide">
            <div className="modal-header">
              <div className="modal-badge">SPEC 14.1 TURN TRACE</div>
              <h3>Turn Trace: {selectedTrace.turn_id}</h3>
            </div>

            <div className="trace-grid">
              <div className="trace-item">
                <span className="trace-label">Intent Classified</span>
                <span className="trace-val">{selectedTrace.intent || 'N/A'}</span>
              </div>
              <div className="trace-item">
                <span className="trace-label">Route Type</span>
                <span className="trace-val">{selectedTrace.route_type || 'model'}</span>
              </div>
              <div className="trace-item">
                <span className="trace-label">Model Used</span>
                <span className="trace-val">{selectedTrace.model_used || 'Groq Llama 3 70B'}</span>
              </div>
              <div className="trace-item">
                <span className="trace-label">Latency</span>
                <span className="trace-val">{selectedTrace.latency_ms} ms</span>
              </div>
              <div className="trace-item">
                <span className="trace-label">Grounding Score</span>
                <span className="trace-val">
                  {selectedTrace.grounding_score !== undefined
                    ? `${(selectedTrace.grounding_score * 100).toFixed(1)}%`
                    : '100%'}
                </span>
              </div>
              <div className="trace-item">
                <span className="trace-label">Tokens</span>
                <span className="trace-val">
                  Prompt: {selectedTrace.tokens_prompt || 0} | Compl: {selectedTrace.tokens_completion || 0}
                </span>
              </div>
            </div>

            <div className="trace-tools-box">
              <span className="trace-label">Tool Calls &amp; Arguments:</span>
              <pre className="code-box">
                {JSON.stringify(selectedTrace.tool_calls_json || [], null, 2)}
              </pre>
            </div>

            <div className="modal-actions">
              <button onClick={() => setSelectedTrace(null)} className="btn-secondary">
                Close Trace
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
