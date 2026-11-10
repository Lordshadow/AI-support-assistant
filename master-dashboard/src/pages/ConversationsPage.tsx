import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ConversationSummary, ConversationTurn, Spec14Trace } from '../types/schemas';
import {
  Panel,
  Button,
  StatusBadge,
  Modal,
  TableSkeleton,
  EmptyState,
} from '../components/ui';
import {
  MessageSquare,
  Eye,
  Cpu,
  Sparkles,
  Database,
  Terminal,
  CheckCircle2,
} from 'lucide-react';

export const ConversationsPage: React.FC<{ showToast?: (type: any, msg: string) => void }> = () => {
  const { staff, requireStepUpWithAction } = useAuth();
  const [searchParams] = useSearchParams();

  const [selectedConv, setSelectedConv] = useState<ConversationSummary | null>(null);
  const [channelFilter, setChannelFilter] = useState('');
  const [handoffFilter, setHandoffFilter] = useState('');
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const [selectedTraceTurn, setSelectedTraceTurn] = useState<ConversationTurn | null>(null);
  const [traceData, setTraceData] = useState<Spec14Trace | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);

  // Unmask modal state
  const [unmaskOpen, setUnmaskOpen] = useState(false);
  const [unmaskReason, setUnmaskReason] = useState('');
  const [unmaskedData, setUnmaskedData] = useState<any[] | null>(null);
  const [unmaskError, setUnmaskError] = useState<string | null>(null);

  const isManagerOrAdmin = staff?.role === 'manager' || staff?.role === 'admin';

  // 1. Fetch conversations list
  const selectedConvId = searchParams.get('conv_id') || '';
  const { data: convData, isLoading: listLoading, isError: listError, refetch } = useQuery<{ conversations: ConversationSummary[]; count: number; total?: number }>({
    queryKey: ['conversationsList', selectedConvId, channelFilter, handoffFilter, page],
    queryFn: async () => {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
      if (selectedConvId) params.set('conv_id', selectedConvId);
      if (channelFilter) params.set('channel', channelFilter);
      if (handoffFilter) params.set('handoff_state', handoffFilter);
      const resp = await api.get(`/api/admin/v1/conversations?${params.toString()}`);
      const list = resp.data?.conversations || [];
      if (list.length > 0 && !selectedConv) {
        setSelectedConv(list[0]);
      }
      return resp.data || { conversations: [], count: 0, total: 0 };
    },
    refetchInterval: 20000,
  });

  const activeConv = selectedConv || convData?.conversations[0] || null;

  useEffect(() => {
    const match = convData?.conversations.find((conversation) => conversation.conv_id === selectedConvId);
    if (match) setSelectedConv(match);
    else if (selectedConv && !convData?.conversations.some((conversation) => conversation.conv_id === selectedConv.conv_id)) {
      setSelectedConv(convData?.conversations[0] || null);
    }
  }, [convData, selectedConvId]);

  // 2. Fetch turns for active conversation
  const { data: turnsData, isLoading: turnsLoading, isError: turnsError, refetch: refetchTurns } = useQuery({
    queryKey: ['conversationTurns', activeConv?.conv_id],
    queryFn: async () => {
      if (!activeConv) return [];
      const resp = await api.get(`/api/admin/v1/conversations/${activeConv.conv_id}`);
      return resp.data?.turns || [];
    },
    enabled: !!activeConv,
  });

  // 3. Inspect "Why this answer" trace (Spec 14.1)
  const handleInspectTrace = async (turn: ConversationTurn) => {
    if (!activeConv) return;
    setSelectedTraceTurn(turn);
    setTraceLoading(true);
    setTraceData(null);
    setTraceError(null);
    try {
      const resp = await api.get(
        `/api/admin/v1/conversations/${activeConv.conv_id}/turns/${turn.turn_id}/trace`
      );
      setTraceData(resp.data as Spec14Trace);
    } catch {
      setTraceError('The trace could not be loaded. Check your connection and retry.');
    } finally {
      setTraceLoading(false);
    }
  };

  // 4. Handle PII unmasking
  const handleUnmaskSubmit = () => {
    if (!unmaskReason.trim() || unmaskReason.length < 10) {
      setUnmaskError('A compliance or escalation rationale of at least 10 characters is required.');
      return;
    }

    requireStepUpWithAction(async () => {
      try {
        const resp = await api.post(`/api/admin/v1/conversations/${activeConv?.conv_id}/unmask`, {
          reason: unmaskReason.trim(),
        });
        setUnmaskedData(resp.data?.unmasked_turns || []);
        setUnmaskOpen(false);
        setUnmaskReason('');
      } catch (err: any) {
        setUnmaskError(err.response?.data?.detail || 'Failed to unmask customer PII dialogue.');
      }
    });
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="micro-label">SPEC 14 & 16.4 • EXPLAINABILITY</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
            Conversation Viewer & Trace Inspector
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1">
            Audit dialogue history with DPDP customer privacy masking and verify per-turn decision traces (R5).
          </p>
        </div>

        <div className="flex items-center gap-3">
          {isManagerOrAdmin && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setUnmaskOpen(true)}
              leftIcon={<Eye className="w-3.5 h-3.5" />}
            >
              Unmask PII (Audited)
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
          >
            Refresh List
          </Button>
        </div>
      </div>

      {/* Split Layout: Sessions List (4 cols) & Dialogue/Trace (8 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Conversations List */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between px-2">
            <span className="text-xs font-bold uppercase tracking-wider text-[#84ABA6]">
              Sessions ({convData?.total ?? convData?.count ?? '—'})
            </span>
            <span className="text-xs text-[#3FD2C0]">Live Stream</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="text-[11px] text-[#84ABA6]">Channel<select aria-label="Filter conversations by channel" value={channelFilter} onChange={(event) => { setChannelFilter(event.target.value); setPage(0); }} className="mt-1 w-full p-2 rounded-lg bg-[#0B4A47] border border-[rgba(63,210,192,0.2)] text-xs text-[#EAF6F4]"><option value="">All channels</option><option value="web">Web</option><option value="whatsapp">WhatsApp</option></select></label>
            <label className="text-[11px] text-[#84ABA6]">Handoff<select aria-label="Filter conversations by handoff state" value={handoffFilter} onChange={(event) => { setHandoffFilter(event.target.value); setPage(0); }} className="mt-1 w-full p-2 rounded-lg bg-[#0B4A47] border border-[rgba(63,210,192,0.2)] text-xs text-[#EAF6F4]"><option value="">All states</option><option value="none">None</option><option value="open">Open</option><option value="assigned">Assigned</option><option value="resolved">Resolved</option><option value="bot">Bot</option></select></label>
          </div>

          {listLoading ? (
            <TableSkeleton rows={6} />
          ) : listError ? (
            <div role="alert" className="space-y-2 p-3 text-sm text-[#FF8585]">Conversation list could not be loaded.<Button size="sm" variant="secondary" onClick={() => refetch()}>Retry</Button></div>
          ) : (
            <div className="space-y-2 max-h-[720px] overflow-y-auto pr-1">
              {(convData?.conversations || []).map((c) => {
                const isSelected = activeConv?.conv_id === c.conv_id;
                return (
                  <div
                    key={c.conv_id}
                    onClick={() => {
                      setSelectedConv(c);
                      setSelectedTraceTurn(null);
                      setTraceData(null);
                      setUnmaskedData(null);
                    }}
                    className={`p-3.5 rounded-2xl transition-all duration-150 cursor-pointer border ${
                      isSelected
                        ? 'bg-[rgba(11,74,71,0.9)] border-[#3FD2C0] shadow-[0_4px_16px_rgba(63,210,192,0.2)]'
                        : 'glass-panel border-[rgba(63,210,192,0.15)] hover:border-[rgba(63,210,192,0.3)] hover:bg-[rgba(11,74,71,0.5)]'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <span className="text-xs font-bold font-mono text-[#EAF6F4]">
                        {c.conv_id}
                      </span>
                      <StatusBadge
                        status={c.handoff_state === 'escalated' ? 'warning' : 'neutral'}
                        label={c.handoff_state === 'escalated' ? 'Escalated' : c.channel}
                        size="sm"
                      />
                    </div>
                    <div className="flex items-center justify-between text-xs text-[#B6D5D1]">
                      <span>Customer: {c.customer_id}</span>
                      <span>{c.turn_count} turns</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {!listLoading && !listError && <div className="flex items-center justify-between text-xs text-[#84ABA6]"><span>Page {page + 1} of {Math.max(1, Math.ceil((convData?.total || 0) / pageSize))}</span><div className="flex gap-2"><Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>Previous</Button><Button size="sm" variant="ghost" disabled={(page + 1) * pageSize >= (convData?.total || 0)} onClick={() => setPage((current) => current + 1)}>Next</Button></div></div>}
        </div>

        {/* Right: Dialogue Transcript & "Why this answer" Drawer */}
        <div className="lg:col-span-8 space-y-6">
          {activeConv ? (
            <Panel
              tier="data"
              notchedLabel="CONVERSATION DIALOGUE"
              notchedIcon={<MessageSquare className="w-3.5 h-3.5 text-[#3FD2C0]" />}
              className="space-y-5"
            >
              {/* Dialogue Transcript Meta Header */}
              <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-[rgba(63,210,192,0.18)] text-xs text-[#B6D5D1]">
                <div className="flex items-center gap-4">
                  <span>Session: <strong className="font-mono text-[#EAF6F4]">{activeConv.conv_id}</strong></span>
                  <span>Channel: <strong className="capitalize text-[#3FD2C0]">{activeConv.channel}</strong></span>
                  <span>Handoff: <strong className="text-[#FFA502]">{activeConv.handoff_state}</strong></span>
                </div>
                {unmaskedData && (
                  <span className="text-[11px] font-bold text-[#FFA502] bg-[rgba(255,165,2,0.15)] px-2.5 py-0.5 rounded-full border border-[rgba(255,165,2,0.3)]">
                    PII Unmasked (Audited)
                  </span>
                )}
              </div>

              {/* Dialogue Turns */}
              {turnsLoading ? (
                <div className="space-y-4 py-8">
                  <TableSkeleton rows={4} />
                </div>
              ) : turnsError ? (
                <div role="alert" className="space-y-3 py-8 text-center text-sm text-[#FF8585]">Conversation turns could not be loaded.<Button size="sm" variant="secondary" onClick={() => refetchTurns()}>Retry</Button></div>
              ) : (turnsData || []).length === 0 ? (
                <div className="text-center py-12 text-sm text-[#84ABA6]">
                  No turns recorded for this conversation.
                </div>
              ) : (
                <div className="space-y-4 max-h-[460px] overflow-y-auto pr-2">
                  {(turnsData || []).map((turn: ConversationTurn, idx: number) => {
                    const isSelected = selectedTraceTurn?.turn_id === turn.turn_id;
                    const unmaskMatch = unmaskedData?.find((u) => u.turn_id === turn.turn_id);
                    const userText = unmaskMatch?.user_raw || turn.user_masked;
                    const assistantText = unmaskMatch?.assistant_raw || turn.assistant_masked;

                    return (
                      <div
                        key={turn.turn_id}
                        className={`p-4 rounded-2xl border transition-all ${
                          isSelected
                            ? 'bg-[rgba(11,74,71,0.7)] border-[#3FD2C0]'
                            : 'bg-[rgba(4,30,29,0.6)] border-[rgba(63,210,192,0.12)]'
                        }`}
                      >
                        {/* Turn Header */}
                        <div className="flex items-center justify-between text-xs mb-3">
                          <span className="font-mono font-bold text-[#3FD2C0]">
                            Turn #{turn.step_index || idx + 1}
                          </span>
                          <div className="flex items-center gap-2">
                            {turn.intent && (
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-[rgba(11,74,71,0.8)] border border-[rgba(63,210,192,0.2)] text-[#B6D5D1]">
                                {turn.intent}
                              </span>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-[11px] py-0.5 px-2.5 text-[#3FD2C0] hover:bg-[rgba(63,210,192,0.1)] border border-[rgba(63,210,192,0.25)] rounded-full"
                              onClick={() => handleInspectTrace(turn)}
                              leftIcon={<Sparkles className="w-3 h-3" />}
                            >
                              Why this answer?
                            </Button>
                          </div>
                        </div>

                        {/* Customer Speech Bubble */}
                        <div className="mb-3 pl-3 border-l-2 border-[#FFA502]">
                          <span className="text-[10px] uppercase font-bold tracking-wider text-[#FFA502] block mb-0.5">
                            Customer
                          </span>
                          <p className="text-sm text-[#EAF6F4] leading-relaxed whitespace-pre-wrap">
                            {userText}
                          </p>
                        </div>

                        {/* Assistant Speech Bubble */}
                        <div className="pl-3 border-l-2 border-[#3FD2C0]">
                          <span className="text-[10px] uppercase font-bold tracking-wider text-[#3FD2C0] block mb-0.5">
                            Assistant
                          </span>
                          <div className="text-sm text-[#B6D5D1] leading-relaxed whitespace-pre-wrap font-sans">
                            {assistantText}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>
          ) : (
            <EmptyState
              title="No Conversation Selected"
              description="Choose a conversation session from the list on the left to review its transcript and decision traces."
            />
          )}

          {/* "Why This Answer" Trace Inspector Panel (Spec 14.1 / R5) */}
          {selectedTraceTurn && (
            <Panel
              tier="data"
              notchedLabel="WHY THIS ANSWER? (SPEC 14.1 TRACE)"
              notchedIcon={<Cpu className="w-3.5 h-3.5 text-[#3FD2C0]" />}
              className="space-y-5 animate-in slide-in-from-bottom-3 duration-200"
            >
              {traceLoading ? (
                <TableSkeleton rows={4} />
              ) : traceError ? (
                <div role="alert" className="flex items-center justify-between gap-3 text-sm text-[#FF8585]">
                  <span>{traceError}</span>
                  <Button variant="secondary" size="sm" onClick={() => handleInspectTrace(selectedTraceTurn)}>Retry</Button>
                </div>
              ) : traceData ? (
                <div className="space-y-4">
                  {/* Top Trace Metric Chips */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.2)]">
                      <span className="text-[10px] uppercase font-bold tracking-wider text-[#84ABA6] block">
                        Route Taken
                      </span>
                      <span className="text-xs font-mono font-bold text-[#3FD2C0] capitalize">
                        {traceData.route_taken || 'Not recorded'}
                      </span>
                    </div>

                    <div className="p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.2)]">
                      <span className="text-[10px] uppercase font-bold tracking-wider text-[#84ABA6] block">
                        Intent & Conf.
                      </span>
                      <span className="text-xs font-mono font-bold text-[#EAF6F4]">
                        {traceData.intent || 'Not recorded'}{traceData.intent_confidence != null ? ` (${Math.round(traceData.intent_confidence * 100)}%)` : ''}
                      </span>
                    </div>

                    <div className="p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.2)]">
                      <span className="text-[10px] uppercase font-bold tracking-wider text-[#84ABA6] block">
                        Grounding Check
                      </span>
                      <div className="flex items-center gap-1 mt-0.5">
                        <CheckCircle2 className="w-3.5 h-3.5 text-[#2ED573]" />
                        <span className="text-xs font-mono font-bold text-[#2ED573]">
                          {traceData.grounding_score != null ? `${Math.round(traceData.grounding_score * 100)}%` : 'Not recorded'}{traceData.grounding_result ? ` (${traceData.grounding_result})` : ''}
                        </span>
                      </div>
                    </div>

                    <div className="p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.2)]">
                      <span className="text-[10px] uppercase font-bold tracking-wider text-[#84ABA6] block">
                        Latency & Cost
                      </span>
                      <span className="text-xs font-mono font-bold text-[#EAF6F4]">
                        {traceData.latency_ms != null ? `${traceData.latency_ms}ms` : 'Latency unavailable'} • {traceData.cost_inr != null ? `₹${traceData.cost_inr}` : 'Cost unavailable'}
                      </span>
                    </div>
                  </div>

                  {/* Retrieved Knowledge Chunks (Spec 14.1) */}
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-widest text-[#84ABA6] mb-2 flex items-center gap-1.5">
                      <Database className="w-3.5 h-3.5 text-[#3FD2C0]" />
                      <span>Retrieved Knowledge Evidence ({traceData.retrieved_chunks?.length || 0} Chunks)</span>
                    </h3>
                    <div className="space-y-2">
                      {(traceData.retrieved_chunks || []).map((chk, i) => (
                        <div
                          key={chk.chunk_id || i}
                          className="p-3 rounded-xl bg-[rgba(4,30,29,0.7)] border border-[rgba(63,210,192,0.15)] text-xs"
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-bold text-[#EAF6F4]">{chk.title || chk.chunk_id}</span>
                            <span className="font-mono text-[#3FD2C0] text-[11px]">
                              Similarity Score: {Math.round(chk.score * 100)}%
                            </span>
                          </div>
                          {chk.text && <p className="text-[#B6D5D1] italic">"{chk.text}"</p>}
                        </div>
                      ))}
                      {(!traceData.retrieved_chunks || traceData.retrieved_chunks.length === 0) && <p className="text-xs text-[#84ABA6]">No retrieval evidence was recorded for this turn.</p>}
                    </div>
                  </div>

                  {/* Tool Execution Calls (Spec 14.1 Masked Arguments) */}
                  {traceData.tool_calls && traceData.tool_calls.length > 0 && (
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-widest text-[#84ABA6] mb-2 flex items-center gap-1.5">
                        <Terminal className="w-3.5 h-3.5 text-[#3FD2C0]" />
                        <span>Deterministic Tool Invocations</span>
                      </h3>
                      <div className="space-y-2">
                        {traceData.tool_calls.map((tool, i) => (
                          <div
                            key={i}
                            className="p-3 rounded-xl bg-[rgba(4,30,29,0.7)] border border-[rgba(63,210,192,0.15)] font-mono text-xs text-[#B6D5D1]"
                          >
                            <span className="text-[#3FD2C0] font-bold">{tool.tool || tool.name || tool.tool_name || 'Tool'}()</span>
                            <pre className="mt-1 text-[11px] text-[#84ABA6] overflow-x-auto">
                              {JSON.stringify(tool.arguments, null, 2)}
                            </pre>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Model & Prompt Telemetry */}
                  <div className="p-3 rounded-xl bg-[rgba(11,74,71,0.4)] border border-[rgba(63,210,192,0.18)] text-xs flex flex-wrap items-center justify-between gap-3 text-[#B6D5D1]">
                    {traceData.model_name && <span>Model: <strong className="text-[#EAF6F4] font-mono">{traceData.model_name}</strong></span>}
                    {traceData.prompt_version && <span>Prompt Version: <strong className="text-[#3FD2C0] font-mono">{traceData.prompt_version}</strong></span>}
                    {(traceData.tokens_prompt != null || traceData.tokens_completion != null) && <span>Tokens: <strong className="text-[#EAF6F4] font-mono">{traceData.tokens_prompt ?? '—'} prompt / {traceData.tokens_completion ?? '—'} completion</strong></span>}
                  </div>
                </div>
              ) : null}
            </Panel>
          )}
        </div>
      </div>

      {/* PII Unmasking Modal */}
      <Modal
        isOpen={unmaskOpen}
        onClose={() => setUnmaskOpen(false)}
        title="Unmask Customer PII (DPDP Act Compliance)"
        description="Customer phone numbers, addresses, and raw dialogue are protected by default. Access requires Step-Up authentication and writes an immutable audit record."
        maxWidth="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setUnmaskOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleUnmaskSubmit} leftIcon={<Eye className="w-4 h-4" />}>
              Elevate & Reveal
            </Button>
          </>
        }
      >
        <div className="space-y-3 pt-2">
          {unmaskError && (
            <div className="p-3 rounded-xl bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.4)] text-[#FF8585] text-xs">
              {unmaskError}
            </div>
          )}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-[#B6D5D1] mb-1.5">
              Escalation / Compliance Rationale (Min 10 chars)
            </label>
            <textarea
              rows={3}
              value={unmaskReason}
              onChange={(e) => setUnmaskReason(e.target.value)}
              placeholder="e.g. Customer requested grievance escalation for duplicate charge dispute."
              className="w-full p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] placeholder-[#84ABA6] focus:border-[#3FD2C0] text-sm outline-none resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
};
