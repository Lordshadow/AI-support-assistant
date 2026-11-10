import React, { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { EscalationTicket } from '../types/schemas';
import {
  Panel,
  Button,
  StatusBadge,
  Tabs,
  Modal,
  TableSkeleton,
  EmptyState,
} from '../components/ui';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  UserCheck,
} from 'lucide-react';

export const EscalationsPage: React.FC = () => {
  const { staff } = useAuth();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();

  const [activeTab, setActiveTab] = useState<'all' | 'open' | 'assigned' | 'resolved'>('all');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const [selectedTicket, setSelectedTicket] = useState<EscalationTicket | null>(null);
  const [resolveModalOpen, setResolveModalOpen] = useState(false);
  const [resolutionNote, setResolutionNote] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // 1. Fetch escalations
  const selectedEscalationId = searchParams.get('esc_id') || '';
  const { data: escalationsData, isLoading, isError: listError, refetch } = useQuery<{ escalations: EscalationTicket[]; count: number; total?: number }>({
    queryKey: ['escalationsList', activeTab, priorityFilter, page, selectedEscalationId],
    queryFn: async () => {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
      if (activeTab !== 'all') params.set('state', activeTab);
      if (priorityFilter) params.set('priority', priorityFilter);
      if (selectedEscalationId) params.set('esc_id', selectedEscalationId);
      const resp = await api.get(`/api/admin/v1/escalations?${params.toString()}`);
      return resp.data || { escalations: [], count: 0 };
    },
    refetchInterval: 15000,
  });

  const tickets = escalationsData?.escalations || [];

  useEffect(() => {
    if (selectedEscalationId) {
      const match = tickets.find((ticket) => ticket.esc_id === selectedEscalationId);
      if (match) setSelectedTicket(match);
    }
  }, [tickets, selectedEscalationId]);

  // Claim mutation
  const claimMutation = useMutation({
    mutationFn: async (escId: string) => {
      const resp = await api.post(`/api/admin/v1/escalations/${escId}/claim`);
      return resp.data;
    },
    onSuccess: (_, escId) => {
      setSuccessMsg(`Ticket #${escId} claimed successfully. Assistant bot is silenced for customer session.`);
      setErrorMsg(null);
      queryClient.invalidateQueries({ queryKey: ['escalationsList'] });
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail;
      setErrorMsg(typeof detail === 'string' ? detail : 'Conflict: Ticket was already claimed.');
    },
  });

  // Resolve mutation
  const resolveMutation = useMutation({
    mutationFn: async ({ escId, note }: { escId: string; note: string }) => {
      const resp = await api.post(`/api/admin/v1/escalations/${escId}/resolve`, {
        resolution_note: note,
      });
      return resp.data;
    },
    onSuccess: (_, variables) => {
      setSuccessMsg(`Ticket #${variables.escId} successfully resolved and closed.`);
      setResolveModalOpen(false);
      setResolutionNote('');
      setErrorMsg(null);
      queryClient.invalidateQueries({ queryKey: ['escalationsList'] });
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail;
      setErrorMsg(typeof detail === 'string' ? detail : 'Failed to resolve ticket.');
    },
  });

  const handleClaim = (ticket: EscalationTicket) => {
    setErrorMsg(null);
    setSuccessMsg(null);
    claimMutation.mutate(ticket.esc_id);
  };

  const handleOpenResolve = (ticket: EscalationTicket) => {
    setSelectedTicket(ticket);
    setResolutionNote('');
    setErrorMsg(null);
    setResolveModalOpen(true);
  };

  const handleResolveSubmit = () => {
    if (!selectedTicket || !resolutionNote.trim() || resolutionNote.length < 10) {
      setErrorMsg('A resolution note of at least 10 characters is required to resolve this ticket.');
      return;
    }
    resolveMutation.mutate({
      escId: selectedTicket.esc_id,
      note: resolutionNote.trim(),
    });
  };

  const tabsConfig = [
    { id: 'all', label: 'All Tickets' },
    { id: 'open', label: 'Open' },
    { id: 'assigned', label: 'In Progress' },
    { id: 'resolved', label: 'Resolved' },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="micro-label">SPEC 16.4 • HUMAN TAKEOVER</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
            Escalations Console
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1">
            Manage conversations handed over from the AI assistant. Claiming a ticket silences the bot.
          </p>
        </div>

        <Tabs
          tabs={tabsConfig}
          activeTab={activeTab}
          onChange={(tab) => { setActiveTab(tab as any); setPage(0); }}
          size="sm"
        />
      </div>

      {successMsg && (
        <div className="p-4 rounded-2xl bg-[rgba(46,213,115,0.15)] border border-[rgba(46,213,115,0.4)] text-[#2ED573] text-sm flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {errorMsg && (
        <div className="p-4 rounded-2xl bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.4)] text-[#FF8585] text-sm flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <label className="text-xs text-[#84ABA6]">Priority filter<select aria-label="Filter escalations by priority" value={priorityFilter} onChange={(event) => { setPriorityFilter(event.target.value); setPage(0); }} className="ml-2 p-2 rounded-lg bg-[#0B4A47] border border-[rgba(63,210,192,0.2)] text-xs text-[#EAF6F4]"><option value="">All priorities</option><option value="urgent">Urgent</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
        <Button size="sm" variant="ghost" onClick={() => refetch()}>Refresh</Button>
      </div>

      {/* Escalations Table / List */}
      <Panel
        tier="data"
        notchedLabel="QUEUE TICKETS"
        notchedIcon={<AlertTriangle className="w-3.5 h-3.5 text-[#3FD2C0]" />}
      >
        {isLoading ? (
          <TableSkeleton rows={5} />
        ) : listError ? (
          <div role="alert" className="space-y-3 py-5 text-sm text-[#FF8585]">Escalations could not be loaded.<Button size="sm" variant="secondary" onClick={() => refetch()}>Retry</Button></div>
        ) : tickets.length === 0 ? (
          <EmptyState
            variant="cleared"
            title="No Escalation Backlog"
            description="All escalated customer requests in this filter have been claimed or resolved."
            actionLabel="Refresh List"
            onAction={() => refetch()}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-[rgba(63,210,192,0.2)] text-[11px] uppercase tracking-wider text-[#84ABA6]">
                  <th className="py-3 px-4 font-bold">Ticket ID</th>
                  <th className="py-3 px-4 font-bold">Reason & Summary</th>
                  <th className="py-3 px-4 font-bold">Priority</th>
                  <th className="py-3 px-4 font-bold">Wait Time</th>
                  <th className="py-3 px-4 font-bold">Status & Assignee</th>
                  <th className="py-3 px-4 font-bold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgba(63,210,192,0.1)]">
                {tickets.map((t) => {
                  const isAssignedToMe = t.assigned_to === staff?.staffId;
                  return (
                    <tr key={t.esc_id} className="hover:bg-[rgba(11,74,71,0.3)] transition-colors">
                      <td className="py-3.5 px-4 font-mono font-bold text-[#EAF6F4]">
                        {t.esc_id}
                        <span className="block text-[11px] font-normal text-[#84ABA6]">
                          {t.conv_id}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 max-w-xs">
                        <span className="font-semibold text-[#EAF6F4] block capitalize">
                          {t.reason.replace(/_/g, ' ')}
                        </span>
                        <span className="text-xs text-[#B6D5D1] line-clamp-1">
                          {t.summary}
                        </span>
                      </td>

                      <td className="py-3.5 px-4">
                        <StatusBadge
                          status={t.priority === 'urgent' ? 'danger' : t.priority === 'high' ? 'warning' : 'info'}
                          label={t.priority.toUpperCase()}
                          size="sm"
                        />
                      </td>

                      <td className="py-3.5 px-4 font-mono text-xs text-[#FFA502]">
                        <span className="flex items-center gap-1">
                          <Clock className="w-3.5 h-3.5" />
                          {t.wait_minutes} min
                        </span>
                      </td>

                      <td className="py-3.5 px-4">
                        {t.state === 'open' ? (
                          <StatusBadge status="pending" label="Unclaimed" size="sm" />
                        ) : t.state === 'assigned' ? (
                          <span className="text-xs text-[#3FD2C0] flex items-center gap-1 font-semibold">
                            <UserCheck className="w-3.5 h-3.5" />
                            {isAssignedToMe ? 'Assigned to you' : t.assigned_to}
                          </span>
                        ) : (
                          <StatusBadge status="success" label="Resolved" size="sm" />
                        )}
                      </td>

                      <td className="py-3.5 px-4 text-right">
                        {t.state === 'open' ? (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => handleClaim(t)}
                            isLoading={claimMutation.isPending}
                          >
                            Claim Ticket
                          </Button>
                        ) : t.state === 'assigned' ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handleOpenResolve(t)}
                          >
                            Resolve Ticket
                          </Button>
                        ) : (
                          <span className="text-xs text-[#84ABA6] italic">Closed</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {!isLoading && !listError && tickets.length > 0 && <div className="mt-4 flex items-center justify-between text-xs text-[#84ABA6]"><span>Page {page + 1} of {Math.max(1, Math.ceil((escalationsData?.total || 0) / pageSize))}</span><div className="flex gap-2"><Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>Previous</Button><Button size="sm" variant="ghost" disabled={(page + 1) * pageSize >= (escalationsData?.total || 0)} onClick={() => setPage((current) => current + 1)}>Next</Button></div></div>}
      </Panel>

      {/* Resolution Modal */}
      <Modal
        isOpen={resolveModalOpen}
        onClose={() => setResolveModalOpen(false)}
        title="Resolve Escalation Ticket"
        description={`Document your resolution outcome for ticket #${selectedTicket?.esc_id}. This note is permanently recorded for auditability.`}
        maxWidth="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setResolveModalOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleResolveSubmit}
              isLoading={resolveMutation.isPending}
            >
              Confirm Resolution
            </Button>
          </>
        }
      >
        <div className="space-y-3 pt-2">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-[#B6D5D1] mb-1.5">
              Resolution Note (Required, min 10 chars)
            </label>
            <textarea
              rows={4}
              value={resolutionNote}
              onChange={(e) => setResolutionNote(e.target.value)}
              placeholder="e.g. Verified customer invoice and initiated courier re-dispatch for damaged package."
              className="w-full p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] placeholder-[#84ABA6] focus:border-[#3FD2C0] text-sm outline-none resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
};
