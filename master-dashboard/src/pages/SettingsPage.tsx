import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { TenantSettings } from '../types/schemas';
import {
  Panel,
  Button,
  Modal,
  TableSkeleton,
} from '../components/ui';
import {
  Save,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Coins,
  Sliders,
  ShieldAlert,
} from 'lucide-react';

export const SettingsPage: React.FC = () => {
  const { staff } = useAuth();
  const queryClient = useQueryClient();

  const isManagerOrAdmin = staff?.role === 'manager' || staff?.role === 'admin';

  // 1. Fetch current settings
  const { data: currentSettings, isLoading, isError, refetch } = useQuery<TenantSettings>({
    queryKey: ['tenantSettings'],
    queryFn: async () => {
      const resp = await api.get('/api/admin/v1/settings');
      return resp.data;
    },
  });

  // Local form state
  const [formData, setFormData] = useState<Partial<TenantSettings>>({});
  const [diffModalOpen, setDiffModalOpen] = useState(false);
  const [detectedDiff, setDetectedDiff] = useState<Record<string, { old: any; new: any }>>({});
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Initialize form when data loads
  React.useEffect(() => {
    if (currentSettings) {
      setFormData(currentSettings);
    }
  }, [currentSettings]);

  const handleChange = (field: keyof TenantSettings, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleReviewDiff = (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentSettings) return;

    // Compute diff
    const diff: Record<string, { old: any; new: any }> = {};
    (Object.keys(formData) as (keyof TenantSettings)[]).forEach((key) => {
      const oldVal = currentSettings[key];
      const newVal = formData[key];
      if (JSON.stringify(oldVal) !== JSON.stringify(newVal)) {
        diff[key] = { old: oldVal, new: newVal };
      }
    });

    if (Object.keys(diff).length === 0) {
      setErrorMsg('No changes detected in configuration.');
      return;
    }

    setDetectedDiff(diff);
    setErrorMsg(null);
    setDiffModalOpen(true);
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const resp = await api.put('/api/admin/v1/settings', formData);
      return resp.data;
    },
    onSuccess: (data) => {
      setSuccessMsg(data.message || 'Tenant configuration successfully updated and recorded in audit_events.');
      setDiffModalOpen(false);
      setDetectedDiff({});
      queryClient.invalidateQueries({ queryKey: ['tenantSettings'] });
    },
    onError: (err: any) => {
      const detail = err.response?.data?.detail;
      setErrorMsg(typeof detail === 'string' ? detail : 'Failed to update tenant configuration.');
    },
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="micro-label">SPEC 16.4 SCREEN 6 • GOVERNANCE</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
            System & Tenant Settings
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1">
            Configure refund limits, working hours, spend caps, and grounding thresholds. Each mutation requires visual diff confirmation and writes to audit_events.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {!isManagerOrAdmin && (
            <span className="text-xs text-[#FFA502] flex items-center gap-1 font-semibold bg-[rgba(255,165,2,0.15)] px-3 py-1.5 rounded-full border border-[rgba(255,165,2,0.3)]">
              <ShieldAlert className="w-3.5 h-3.5" />
              Read-Only (Manager/Admin Required to Save)
            </span>
          )}
        </div>
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

      {isLoading ? (
        <TableSkeleton rows={6} />
      ) : isError || !currentSettings ? (
        <Panel tier="data" className="space-y-3"><p role="alert" className="text-sm text-[#FF8585]">Settings could not be loaded. Changes are disabled until current values are available.</p><Button size="sm" variant="secondary" onClick={() => refetch()}>Retry</Button></Panel>
      ) : (
        <form onSubmit={handleReviewDiff} className="space-y-6">
          {/* Section 1: Financial & Spend Controls */}
          <Panel
            tier="data"
            notchedLabel="FINANCIAL THRESHOLDS"
            notchedIcon={<Coins className="w-3.5 h-3.5 text-[#3FD2C0]" />}
            className="space-y-4"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  Auto-Refund Limit (INR)
                </label>
                <input
                  type="number"
                  disabled={!isManagerOrAdmin}
                  value={formData.auto_refund_limit_inr ?? 2000}
                  onChange={(e) => handleChange('auto_refund_limit_inr', Number(e.target.value))}
                  className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] font-mono focus:border-[#3FD2C0] outline-none"
                />
                <span className="text-[11px] text-[#84ABA6] mt-1 block">
                  Refunds above this threshold route to human approval queue.
                </span>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  Daily Spend Cap (INR)
                </label>
                <input
                  type="number"
                  disabled={!isManagerOrAdmin}
                  value={formData.daily_spend_cap_inr ?? 2500}
                  onChange={(e) => handleChange('daily_spend_cap_inr', Number(e.target.value))}
                  className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] font-mono focus:border-[#3FD2C0] outline-none"
                />
                <span className="text-[11px] text-[#84ABA6] mt-1 block">
                  Daily token budget for LLM calls before strict failover.
                </span>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  Monthly Spend Cap (INR)
                </label>
                <input
                  type="number"
                  disabled={!isManagerOrAdmin}
                  value={formData.monthly_spend_cap_inr ?? 50000}
                  onChange={(e) => handleChange('monthly_spend_cap_inr', Number(e.target.value))}
                  className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] font-mono focus:border-[#3FD2C0] outline-none"
                />
                <span className="text-[11px] text-[#84ABA6] mt-1 block">
                  Monthly ceiling enforced across tenant services.
                </span>
              </div>
            </div>
          </Panel>

          {/* Section 2: Operating Hours & Languages */}
          <Panel
            tier="data"
            notchedLabel="OPERATING SCHEDULE"
            notchedIcon={<Clock className="w-3.5 h-3.5 text-[#3FD2C0]" />}
            className="space-y-4"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  Support Hours Start
                </label>
                <input
                  type="time"
                  disabled={!isManagerOrAdmin}
                  value={formData.working_hours_start ?? '09:00'}
                  onChange={(e) => handleChange('working_hours_start', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] font-mono focus:border-[#3FD2C0] outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  Support Hours End
                </label>
                <input
                  type="time"
                  disabled={!isManagerOrAdmin}
                  value={formData.working_hours_end ?? '20:00'}
                  onChange={(e) => handleChange('working_hours_end', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] font-mono focus:border-[#3FD2C0] outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  Tenant Timezone
                </label>
                <input
                  type="text"
                  disabled={!isManagerOrAdmin}
                  value={formData.timezone ?? 'Asia/Kolkata'}
                  onChange={(e) => handleChange('timezone', e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4] font-mono focus:border-[#3FD2C0] outline-none"
                />
              </div>
            </div>
          </Panel>

          {/* Section 3: AI Safety & Grounding Thresholds */}
          <Panel
            tier="data"
            notchedLabel="AI SAFETY & THRESHOLDS"
            notchedIcon={<Sliders className="w-3.5 h-3.5 text-[#3FD2C0]" />}
            className="space-y-4"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  Router Confidence Threshold ({Math.round((formData.confidence_threshold ?? 0.85) * 100)}%)
                </label>
                <input
                  type="range"
                  min="0.5"
                  max="1.0"
                  step="0.05"
                  disabled={!isManagerOrAdmin}
                  value={formData.confidence_threshold ?? 0.85}
                  onChange={(e) => handleChange('confidence_threshold', Number(e.target.value))}
                  className="w-full accent-[#3FD2C0]"
                />
                <span className="text-[11px] text-[#84ABA6] mt-1 block">
                  Queries below this confidence fall back to clarification or supervisor handoff.
                </span>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1.5">
                  RAG Grounding Score Threshold ({Math.round((formData.grounding_threshold ?? 0.90) * 100)}%)
                </label>
                <input
                  type="range"
                  min="0.6"
                  max="1.0"
                  step="0.05"
                  disabled={!isManagerOrAdmin}
                  value={formData.grounding_threshold ?? 0.90}
                  onChange={(e) => handleChange('grounding_threshold', Number(e.target.value))}
                  className="w-full accent-[#3FD2C0]"
                />
                <span className="text-[11px] text-[#84ABA6] mt-1 block">
                  Grounding verifier requires this match percentage to deliver answers without escalation.
                </span>
              </div>
            </div>

            {isManagerOrAdmin && (
              <div className="pt-4 flex justify-end">
                <Button
                  type="submit"
                  variant="primary"
                  size="md"
                  leftIcon={<Save className="w-4 h-4" />}
                >
                  Review Changes & Diff
                </Button>
              </div>
            )}
          </Panel>
        </form>
      )}

      {/* Side-by-Side Diff Confirmation Modal (Spec 16.4 Screen 6) */}
      <Modal
        isOpen={diffModalOpen}
        onClose={() => setDiffModalOpen(false)}
        title="Confirm Configuration Changes (Audit Diff)"
        description="Verify the exact field diff below before committing. These changes will be recorded immutably in audit_events."
        maxWidth="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDiffModalOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => saveMutation.mutate()}
              isLoading={saveMutation.isPending}
            >
              Commit Changes to Audit Log
            </Button>
          </>
        }
      >
        <div className="space-y-3 pt-2">
          <div className="overflow-x-auto rounded-xl border border-[rgba(63,210,192,0.2)]">
            <table className="w-full text-left text-xs">
              <thead className="bg-[rgba(11,74,71,0.6)] text-[10px] uppercase font-bold tracking-wider text-[#84ABA6]">
                <tr>
                  <th className="py-2.5 px-3">Field</th>
                  <th className="py-2.5 px-3">Old Value</th>
                  <th className="py-2.5 px-3">New Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgba(63,210,192,0.1)]">
                {Object.entries(detectedDiff).map(([field, delta]) => (
                  <tr key={field} className="font-mono">
                    <td className="py-2 px-3 font-semibold text-[#EAF6F4]">{field}</td>
                    <td className="py-2 px-3 text-[#FF8585] bg-[rgba(255,82,82,0.1)]">
                      {JSON.stringify(delta.old)}
                    </td>
                    <td className="py-2 px-3 text-[#2ED573] bg-[rgba(46,213,115,0.1)]">
                      {JSON.stringify(delta.new)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Modal>
    </div>
  );
};
