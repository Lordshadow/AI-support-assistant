import React, { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { RefundItem } from '../types/schemas';
import {
  Panel,
  Button,
  StatusBadge,
  ConfirmDialog,
  TableSkeleton,
  EmptyState,
} from '../components/ui';
import {
  CreditCard,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ShieldCheck,
  Package,
  User,
  Clock,
  ArrowRight,
} from 'lucide-react';

export const RefundsPage: React.FC<{ showToast?: (type: any, msg: string) => void }> = () => {
  const { staff, requireStepUpWithAction } = useAuth();
  const queryClient = useQueryClient();
  const now = Date.now();
  const [searchParams] = useSearchParams();

  const [selectedRefund, setSelectedRefund] = useState<RefundItem | null>(null);
  const [staffNote, setStaffNote] = useState('');
  const [confirmAction, setConfirmAction] = useState<'approved' | 'rejected' | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [actionSuccessMsg, setActionSuccessMsg] = useState<string | null>(null);
  const [view, setView] = useState<'pending' | 'history'>('pending');

  // 1. Fetch pending refunds
  const searchRefundId = searchParams.get('refund_id') || '';
  const { data: refunds = [], isLoading, isError: refundsError, refetch } = useQuery<RefundItem[]>({
    queryKey: ['refunds', view, searchRefundId],
    queryFn: async () => {
      const endpoint = view === 'pending' ? 'pending' : 'history';
      const resp = await api.get(`/api/admin/v1/refunds/${endpoint}`, { params: view === 'pending' && searchRefundId ? { refund_id: searchRefundId } : undefined });
      const data = resp.data || [];
      // Select first item by default if none selected
      if (data.length > 0 && !selectedRefund) {
        setSelectedRefund(data[0]);
      }
      return data;
    },
    refetchInterval: 12000,
  });

  // Keep selected refund in sync with list
  const activeRefund = (selectedRefund ? refunds.find((r) => r.refund_id === selectedRefund.refund_id) : null) || refunds[0] || null;

  useEffect(() => {
    const selectedId = searchParams.get('refund_id');
    if (selectedId) {
      const match = refunds.find((refund) => refund.refund_id === selectedId);
      if (match) setSelectedRefund(match);
    }
  }, [refunds, searchParams]);

  // Check self-approval: staff cannot approve a refund they requested themselves (Spec 15.1.8 [ASSUMPTION])

  // Check executive limit: Support Executives can only approve refunds <= ₹5,000 (Spec 16.4)
  const isAboveExecutiveLimit = !!activeRefund && activeRefund.amount_inr > 5000 && staff?.role === 'executive';

  // Mutation for Approve/Reject
  const decisionMutation = useMutation({
    mutationFn: async ({
      refundId,
      decision,
      notes,
    }: {
      refundId: string;
      decision: 'approved' | 'rejected';
      notes: string;
    }) => {
      const action = decision === 'approved' ? 'approve' : 'reject';
      const resp = await api.post(`/api/admin/v1/refunds/${refundId}/${action}`, {
        notes,
      });
      return resp.data;
    },
    onSuccess: (data, variables) => {
      const amount = Number(data.amount_inr);
      const amountText = Number.isFinite(amount) ? ` Store refund #${data.store_refund_id} for ₹${amount.toLocaleString('en-IN')} was processed.` : '';
      const modeText = data.test_mode && data.money_moved === false ? ' Test mode confirmed; no money moved.' : '';
      setActionSuccessMsg(`Refund #${variables.refundId} was synchronized.${amountText}${modeText}`);
      setStaffNote('');
      setConfirmAction(null);
      queryClient.invalidateQueries({ queryKey: ['refunds'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardReport'] });
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail;
      setErrorMsg(typeof detail === 'string' ? detail : 'Failed to execute refund decision.');
      setConfirmAction(null);
    },
  });

  const handleActionClick = (decision: 'approved' | 'rejected') => {
    setErrorMsg(null);
    setActionSuccessMsg(null);

    if (decision === 'rejected' && !staffNote.trim()) {
      setErrorMsg('A documented staff note is strictly required to reject a refund request.');
      return;
    }


    if (decision === 'approved' && isAboveExecutiveLimit) {
      setErrorMsg('Policy Violation (Spec 16.4): Refunds exceeding ₹5,000 require Manager or Admin supervisory approval.');
      return;
    }

    // Step-Up required if amount > 5000 INR
    if (activeRefund && activeRefund.amount_inr > 5000) {
      requireStepUpWithAction(() => {
        setConfirmAction(decision);
      });
    } else {
      setConfirmAction(decision);
    }
  };

  const executeConfirmedDecision = () => {
    if (!activeRefund || !confirmAction) return;
    decisionMutation.mutate({
      refundId: activeRefund.refund_id,
      decision: confirmAction,
      notes: staffNote.trim(),
    });
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="micro-label">SPEC 16.4 • REVIEW DESK</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
            Refund Approval Queue
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1">
            Review refunds over ₹2,000 and track decisions synchronized with the ApexStore admin panel.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => refetch()}
          leftIcon={<Clock className="w-3.5 h-3.5" />}
        >
          Refresh Queue
        </Button>
      </div>

      <div className="flex gap-2" role="tablist" aria-label="Refund views">
        <Button size="sm" variant={view === 'pending' ? 'primary' : 'secondary'} onClick={() => { setView('pending'); setSelectedRefund(null); setConfirmAction(null); }}>
          Pending approvals
        </Button>
        <Button size="sm" variant={view === 'history' ? 'primary' : 'secondary'} onClick={() => { setView('history'); setSelectedRefund(null); setConfirmAction(null); }}>
          Refund history
        </Button>
      </div>

      {actionSuccessMsg && (
        <div className="p-4 rounded-2xl bg-[rgba(46,213,115,0.15)] border border-[rgba(46,213,115,0.4)] text-[#2ED573] text-sm flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 shrink-0" />
          <span>{actionSuccessMsg}</span>
        </div>
      )}

      {errorMsg && (
        <div className="p-4 rounded-2xl bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.4)] text-[#FF8585] text-sm flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Main Split Layout */}
      {isLoading ? (
        <TableSkeleton rows={6} />
      ) : refundsError ? (
        <Panel tier="data" className="space-y-3"><p role="alert" className="text-sm text-[#FF8585]">Pending refunds could not be loaded. The queue is not confirmed empty.</p><Button size="sm" variant="secondary" onClick={() => refetch()}>Retry</Button></Panel>
      ) : refunds.length === 0 ? (
        <EmptyState
          variant="cleared"
          title={view === 'pending' ? 'Approval Queue Cleared' : 'No refund history yet'}
          description={view === 'pending' ? 'There are no refund requests waiting for staff approval.' : 'Approved, rejected, and processed refunds will appear here.'}
          actionLabel="Check Again"
          onAction={() => refetch()}
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: List of Refund Requests (5 cols) */}
          <div className="lg:col-span-5 space-y-3">
            <div className="flex items-center justify-between px-2">
              <span className="text-xs font-bold uppercase tracking-wider text-[#84ABA6]">
                {view === 'pending' ? 'Pending Requests' : 'Refund History'} ({refunds.length})
              </span>
              <span className="text-xs text-[#3FD2C0]">Sorted by SLA</span>
            </div>

            <div className="space-y-2.5 max-h-[720px] overflow-y-auto pr-1">
              {refunds.map((refund) => {
                const isSelected = activeRefund?.refund_id === refund.refund_id;
                const reqDate = new Date(refund.created_at);
                const waitMin = Math.round((now - reqDate.getTime()) / 60000);

                return (
                  <div
                    key={refund.refund_id}
                    onClick={() => {
                      setSelectedRefund(refund);
                      setErrorMsg(null);
                    }}
                    className={`p-4 rounded-2xl transition-all duration-150 cursor-pointer border ${
                      isSelected
                        ? 'bg-[rgba(11,74,71,0.9)] border-[#3FD2C0] shadow-[0_4px_20px_rgba(63,210,192,0.2)]'
                        : 'glass-panel border-[rgba(63,210,192,0.15)] hover:border-[rgba(63,210,192,0.3)] hover:bg-[rgba(11,74,71,0.5)]'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-sm font-bold font-mono text-[#EAF6F4]">
                        #{refund.refund_id}
                      </span>
                      <span className="text-base font-extrabold font-mono text-[#3FD2C0]">
                        ₹{refund.amount_inr.toLocaleString('en-IN')}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs text-[#B6D5D1] mb-2">
                      <span>Order #{refund.order_id}</span>
                      <span className="flex items-center gap-1 font-mono text-[11px] text-[#FFA502]">
                        <Clock className="w-3 h-3" />
                        {view === 'pending' ? `${waitMin}m waiting` : refund.state.replaceAll('_', ' ')}
                      </span>
                    </div>

                    <p className="text-xs text-[#84ABA6] line-clamp-1 italic">
                      "{refund.reason}"
                    </p>

                    <div className="mt-3 pt-2.5 border-t border-[rgba(63,210,192,0.12)] flex items-center justify-between">
                      <StatusBadge
                        status={view === 'pending' ? (refund.amount_inr > 5000 ? 'warning' : 'info') : (refund.state === 'processed' || refund.state === 'completed' ? 'success' : refund.state === 'rejected' ? 'danger' : 'neutral')}
                        label={view === 'pending' ? (refund.amount_inr > 5000 ? 'High Value (> ₹5k)' : 'Standard Review') : refund.state.replaceAll('_', ' ')}
                        size="sm"
                      />
                      {view === 'pending' && <span className="text-[11px] text-[#3FD2C0] flex items-center gap-1">Inspect <ArrowRight className="w-3 h-3" /></span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Column: Detailed Review Card (7 cols) */}
          {activeRefund && (
            <div className="lg:col-span-7">
              <Panel
                tier="data"
                notchedLabel="REFUND INSPECTION"
                notchedIcon={<CreditCard className="w-3.5 h-3.5 text-[#3FD2C0]" />}
                className="space-y-6"
              >
                {/* Header Information */}
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 pb-4 border-b border-[rgba(63,210,192,0.18)]">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-mono font-bold text-[#84ABA6]">
                        REFUND ID:
                      </span>
                      <span className="text-base font-bold font-mono text-[#EAF6F4]">
                        {activeRefund.refund_id}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-[#B6D5D1]">
                      <span className="flex items-center gap-1">
                        <Package className="w-3.5 h-3.5 text-[#3FD2C0]" />
                        Order: <strong>#{activeRefund.order_id}</strong>
                      </span>
                      <span className="flex items-center gap-1">
                        <User className="w-3.5 h-3.5 text-[#3FD2C0]" />
                        Customer: <strong>{activeRefund.customer_id}</strong>
                      </span>
                    </div>
                  </div>

                  <div className="text-right">
                    <span className="text-xs text-[#84ABA6] uppercase font-bold tracking-wider block">
                      Requested Amount
                    </span>
                    <span className="text-2xl sm:text-3xl font-black font-mono text-[#3FD2C0]">
                      ₹{activeRefund.amount_inr.toLocaleString('en-IN')}
                    </span>
                  </div>
                </div>

                <div className="p-4 rounded-2xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.2)] flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <ShieldCheck className="w-5 h-5 text-[#84ABA6]" />
                    <div>
                      <p className="text-xs font-bold uppercase tracking-wider text-[#EAF6F4]">Customer Trust Level: {activeRefund.customer_trust_level || 'unknown'}</p>
                      <p className="text-xs text-[#B6D5D1]">{activeRefund.customer_trust_level === 'verified' ? 'Verified identity is recorded for this request.' : 'Identity verification evidence was not recorded for this request.'}</p>
                    </div>
                  </div>
                  <StatusBadge status={activeRefund.customer_trust_level === 'verified' ? 'success' : 'neutral'} label={activeRefund.customer_trust_level === 'verified' ? 'Verified' : 'Unavailable'} size="sm" />
                </div>

                {/* Assistant Automated Checks Checklist */}
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-widest text-[#84ABA6] mb-3">
                    Assistant Pre-Approval Checks
                  </h3>
                  <div className="space-y-2">
                    {activeRefund.checks?.length ? activeRefund.checks.map((check) => (
                      <div key={check.name} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-[rgba(6,47,46,0.6)] border border-[rgba(63,210,192,0.15)] text-xs">
                        <div className="flex items-center gap-2.5">
                          {check.passed ? <CheckCircle2 className="w-4 h-4 text-[#2ED573]" /> : <AlertTriangle className="w-4 h-4 text-[#FFA502]" />}
                          <span className="text-[#EAF6F4]">{check.name}</span>
                        </div>
                        <span className={`font-semibold ${check.passed ? 'text-[#2ED573]' : 'text-[#FFA502]'}`}>{check.details || (check.passed ? 'Passed' : 'Not passed')}</span>
                      </div>
                    )) : <p className="text-xs text-[#B6D5D1] p-3 rounded-xl bg-[rgba(6,47,46,0.6)]">No eligibility check details were stored for this request.</p>}
                    {activeRefund.policy_version_applied && <p className="text-[11px] text-[#84ABA6]">Policy version: {activeRefund.policy_version_applied}</p>}
                  </div>
                </div>

                <div>
                  <h3 className="text-xs font-bold uppercase tracking-widest text-[#84ABA6] mb-2">Order items</h3>
                  {activeRefund.order_items?.length ? <ul className="space-y-1 text-xs text-[#B6D5D1]">{activeRefund.order_items.map((item) => <li key={item.item_id}>{item.title} × {item.quantity} · ₹{item.price_inr.toLocaleString('en-IN')} {item.returnable ? '(returnable)' : '(not returnable)'}</li>)}</ul> : <p className="text-xs text-[#B6D5D1]">Order item details are unavailable for this request.</p>}
                </div>

                {/* Customer Stated Reason */}
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-widest text-[#84ABA6] mb-2">
                    Customer Stated Reason
                  </h3>
                  <div className="p-3.5 rounded-xl bg-[rgba(4,30,29,0.7)] border border-[rgba(63,210,192,0.15)] text-sm text-[#EAF6F4] italic">
                    "{activeRefund.reason}"
                  </div>
                </div>

                {/* Executive > ₹5,000 Limit Warning (Spec 16.4) */}
                {isAboveExecutiveLimit && (
                  <div className="p-3.5 rounded-xl bg-[rgba(255,165,2,0.15)] border border-[rgba(255,165,2,0.4)] text-[#FFA502] text-xs flex items-center gap-3">
                    <AlertTriangle className="w-5 h-5 shrink-0" />
                    <span>
                      Spec 16.4 Supervisory Gate: Refunds exceeding ₹5,000 exceed the frontline Support Executive threshold and require supervisory approval by an Operations Manager or Admin.
                    </span>
                  </div>
                )}

                {view === 'history' && (
                  <div className="p-3 rounded-xl bg-[rgba(6,47,46,0.6)] border border-[rgba(63,210,192,0.15)] text-sm text-[#B6D5D1]">
                    Final state: <span className="font-semibold text-[#EAF6F4]">{activeRefund.state.replaceAll('_', ' ')}</span>
                    {activeRefund.decided_at ? ` · ${new Date(activeRefund.decided_at).toLocaleString()}` : ''}
                    {activeRefund.staff_note ? <p className="mt-2">{activeRefund.staff_note}</p> : null}
                  </div>
                )}

                {/* Mandatory Staff Audit Note */}
                {view === 'pending' && <div>
                  <label className="block text-xs font-bold uppercase tracking-widest text-[#B6D5D1] mb-1.5">
                    Staff Audit Note (Required for Rejection)
                  </label>
                  <textarea
                    rows={3}
                    value={staffNote}
                    onChange={(e) => setStaffNote(e.target.value)}
                    placeholder="Document your review rationale or reason for decision. This will be recorded in audit_events."
                    className="w-full p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] placeholder-[#84ABA6] focus:border-[#3FD2C0] focus:ring-1 focus:ring-[#3FD2C0] outline-none text-sm resize-none"
                  />
                </div>}

                {/* Action Buttons */}
                {view === 'pending' && <div className="flex items-center justify-end gap-3 pt-3 border-t border-[rgba(63,210,192,0.15)]">
                  <Button
                    variant="danger"
                    size="md"
                    onClick={() => handleActionClick('rejected')}
                    isLoading={decisionMutation.isPending && confirmAction === 'rejected'}
                    leftIcon={<XCircle className="w-4 h-4" />}
                  >
                    Reject Refund
                  </Button>

                  <Button
                    variant="primary"
                    size="md"
                    disabled={isAboveExecutiveLimit}
                    onClick={() => handleActionClick('approved')}
                    isLoading={decisionMutation.isPending && confirmAction === 'approved'}
                    leftIcon={<CheckCircle2 className="w-4 h-4" />}
                  >
                    {isAboveExecutiveLimit ? 'Requires Manager Sign-Off (> ₹5,000)' : 'Approve and process matched store refund'}
                  </Button>
                </div>}
              </Panel>
            </div>
          )}
        </div>
      )}

      {/* Confirmation Dialog before action */}
      <ConfirmDialog
        isOpen={view === 'pending' && !!confirmAction}
        onClose={() => setConfirmAction(null)}
        onConfirm={executeConfirmedDecision}
        title={confirmAction === 'approved' ? 'Confirm Refund Approval' : 'Confirm Refund Rejection'}
        message={
          confirmAction === 'approved'
            ? `Approve refund #${activeRefund?.refund_id} and process the unique pending refund in ApexStore using the storefront amount. The payment provider result will determine the final state.`
            : `Are you sure you want to reject refund #${activeRefund?.refund_id}? Note recorded: "${staffNote || 'None'}"`
        }
        confirmLabel={confirmAction === 'approved' ? 'Confirm Approval' : 'Confirm Rejection'}
        variant={confirmAction === 'approved' ? 'primary' : 'danger'}
        isLoading={decisionMutation.isPending}
      />
    </div>
  );
};
