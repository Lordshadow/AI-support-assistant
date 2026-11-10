import React, { useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { Panel, Card, Button, StatusBadge, ArchControl, Skeleton } from '../components/ui';
import {
  CreditCard,
  AlertTriangle,
  Clock,
  ShieldCheck,
  Server,
  Zap,
  ArrowRight,
  Database,
  Activity,
} from 'lucide-react';

export const OverviewPage: React.FC = () => {
  const navigate = useNavigate();
  const healthRef = useRef<HTMLDivElement>(null);

  // 1. Fetch pending refunds
  const { data: refunds, isLoading: refundsLoading, isError: refundsError, refetch: refetchRefunds } = useQuery({
    queryKey: ['pendingRefunds'],
    queryFn: async () => {
      const resp = await api.get('/api/admin/v1/refunds/pending');
      return resp.data || [];
    },
    refetchInterval: 15000,
  });

  // 2. Fetch escalations
  const { data: escalationsData, isLoading: escLoading, isError: escalationsError, refetch: refetchEscalations } = useQuery({
    queryKey: ['escalationsSummary'],
    queryFn: async () => {
      const resp = await api.get('/api/admin/v1/escalations?state=open');
      return resp.data || { escalations: [], count: 0 };
    },
    refetchInterval: 15000,
  });

  // 3. Fetch reports & spend metrics
  const { data: reports, isLoading: reportsLoading, isError: reportsError, refetch: refetchReports } = useQuery({
    queryKey: ['dashboardReport'],
    queryFn: async () => {
      const resp = await api.get('/api/admin/v1/reports');
      return resp.data || {};
    },
    refetchInterval: 30000,
  });

  const { data: health } = useQuery({
    queryKey: ['serviceHealth'],
    queryFn: async () => (await api.get('/health')).data,
    refetchInterval: 30000,
    retry: 1,
  });

  const pendingRefundsCount = refunds?.length ?? 0;
  const openEscalationsCount = escalationsData?.count || 0;
  const deflectionRatePct = reports?.deflection_rate == null ? null : Math.round(reports.deflection_rate * 100);
  const dailySpend = reports?.spend_daily_inr;
  const dailyCap = reports?.spend_daily_cap_inr;
  const spendPct = dailySpend == null || !dailyCap ? 0 : Math.min(100, Math.round((dailySpend / dailyCap) * 100));

  // Queue age warning check: any refund older than 30 mins
  const now = Date.now();
  const oldestRefund = (refunds || []).reduce((oldest: any, cur: any) => {
    const age = now - new Date(cur.created_at).getTime();
    return age > (oldest?.age || 0) ? { ...cur, age } : oldest;
  }, null);
  const oldestAgeMinutes = oldestRefund ? Math.round(oldestRefund.age / 60000) : 0;
  const hasQueueAgeWarning = !refundsError && oldestAgeMinutes >= 30;

  const scrollToHealth = () => {
    healthRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Page Title & Micro-Caption */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="micro-label">MISSION CONTROL</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
            Command Center Overview
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1">
            Real-time operating telemetry, human-in-the-loop approval queues, and system health.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate('/refunds')}
            leftIcon={<CreditCard className="w-3.5 h-3.5" />}
          >
            Approvals ({refundsError ? '—' : pendingRefundsCount})
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => navigate('/escalations')}
            leftIcon={<AlertTriangle className="w-3.5 h-3.5" />}
          >
            Escalations ({escalationsError ? '—' : openEscalationsCount})
          </Button>
        </div>
      </div>

      {(refundsError || escalationsError || reportsError) && (
        <div role="alert" className="p-3 rounded-xl border border-[rgba(255,82,82,0.35)] bg-[rgba(255,82,82,0.1)] text-sm text-[#FF8585] flex flex-wrap items-center gap-3">
          <span>Some overview data could not be loaded.</span>
          {refundsError && <Button size="sm" variant="secondary" onClick={() => refetchRefunds()}>Retry refunds</Button>}
          {escalationsError && <Button size="sm" variant="secondary" onClick={() => refetchEscalations()}>Retry escalations</Button>}
          {reportsError && <Button size="sm" variant="secondary" onClick={() => refetchReports()}>Retry reports</Button>}
        </div>
      )}

      {/* Queue Age Warning Banner (Spec 16.4 Screen 1 requirement) */}
      {hasQueueAgeWarning && (
        <div
          role="alert"
          className="p-4 rounded-2xl bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.4)] flex items-center justify-between gap-4 shadow-[0_8px_24px_rgba(255,82,82,0.2)]"
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[rgba(255,82,82,0.2)] flex items-center justify-center text-[#FF5252] shrink-0">
              <Clock className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <p className="text-sm font-bold text-[#FF8585]">
                Queue SLA Warning: Pending Refund Waiting {oldestAgeMinutes} Minutes
              </p>
              <p className="text-xs text-[#B6D5D1]">
                Refund #{oldestRefund?.refund_id} (Order #{oldestRefund?.order_id}) exceeds the 30-minute target review SLA.
              </p>
            </div>
          </div>
          <Button
            variant="danger"
            size="sm"
            onClick={() => navigate('/refunds')}
          >
            Review Now
          </Button>
        </div>
      )}

      {/* 4 Primary KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* KPI 1: Pending Approvals */}
        <Card
          variant="dark"
          microCaption="HUMAN-IN-THE-LOOP"
          title="Pending Approvals"
          actionTitle="Go to approvals queue"
          onAction={() => navigate('/refunds')}
        >
          {refundsLoading ? (
            <Skeleton height="36px" width="50%" />
          ) : (
            <div className="mt-2 flex items-baseline justify-between">
              <span className="text-3xl font-extrabold text-[#EAF6F4] font-mono">
                {refundsError ? 'Unavailable' : pendingRefundsCount}
              </span>
              <StatusBadge
                status={refundsError ? 'warning' : pendingRefundsCount > 5 ? 'warning' : pendingRefundsCount > 0 ? 'info' : 'success'}
                label={refundsError ? 'Load failed' : pendingRefundsCount > 0 ? `${pendingRefundsCount} requests` : 'Queue Clear'}
                size="sm"
              />
            </div>
          )}
          <p className="text-xs text-[#84ABA6] mt-3">
            Refunds exceeding auto-limit (₹2,000) requiring supervisor sign-off.
          </p>
        </Card>

        {/* KPI 2: Open Escalations */}
        <Card
          variant="dark"
          microCaption="HUMAN TAKEOVER"
          title="Open Escalations"
          actionTitle="Go to escalations queue"
          onAction={() => navigate('/escalations')}
        >
          {escLoading ? (
            <Skeleton height="36px" width="50%" />
          ) : (
            <div className="mt-2 flex items-baseline justify-between">
              <span className="text-3xl font-extrabold text-[#EAF6F4] font-mono">
                {escalationsError ? 'Unavailable' : openEscalationsCount}
              </span>
              <StatusBadge
                status={escalationsError ? 'warning' : openEscalationsCount > 3 ? 'danger' : openEscalationsCount > 0 ? 'warning' : 'success'}
                label={escalationsError ? 'Load failed' : openEscalationsCount > 0 ? `${openEscalationsCount} waiting` : 'No backlog'}
                size="sm"
              />
            </div>
          )}
          <p className="text-xs text-[#84ABA6] mt-3">
            Customer inquiries where bot is silenced for human executive takeover.
          </p>
        </Card>

        {/* KPI 3: Deflection Rate */}
        <Card
          variant="dark"
          microCaption="AUTOMATION SUCCESS"
          title="Deflection Rate"
          actionTitle="View reports"
          onAction={() => navigate('/reports')}
        >
          {reportsLoading ? (
            <Skeleton height="36px" width="50%" />
          ) : (
            <div className="mt-2 flex items-baseline justify-between">
              <span className="text-3xl font-extrabold text-[#EAF6F4] font-mono">
                {deflectionRatePct == null ? 'Unavailable' : `${deflectionRatePct}%`}
              </span>
              <StatusBadge
                status={deflectionRatePct == null ? 'warning' : deflectionRatePct >= 80 ? 'success' : 'warning'}
                label={deflectionRatePct == null ? 'No report data' : deflectionRatePct >= 80 ? 'Above Target' : 'Sub-Optimal'}
                size="sm"
              />
            </div>
          )}
          <p className="text-xs text-[#84ABA6] mt-3">
            Inquiries resolved autonomously without escalation (Target: &gt;= 80%).
          </p>
        </Card>

        {/* KPI 4: Spend Today vs Cap */}
        <Card
          variant="dark"
          microCaption="FINANCIAL CONTROL"
          title="Token Spend Today"
          actionTitle="Inspect spend ledger"
          onAction={() => navigate('/reports')}
        >
          {reportsLoading ? (
            <Skeleton height="36px" width="50%" />
          ) : (
            <div>
              <div className="mt-2 flex items-baseline justify-between">
                <span className="text-2xl font-extrabold text-[#EAF6F4] font-mono">
                  {dailySpend == null ? 'Unavailable' : `₹${dailySpend.toLocaleString('en-IN')}`}
                </span>
                <span className="text-xs text-[#84ABA6]">
                  {dailyCap == null ? '' : `Cap: ₹${dailyCap.toLocaleString('en-IN')}`}
                </span>
              </div>
              <div className="w-full h-2 rounded-full bg-[rgba(11,74,71,0.8)] mt-3 overflow-hidden border border-[rgba(63,210,192,0.15)]">
                <div
                  className={`h-full transition-all duration-300 rounded-full ${
                    spendPct >= 95 ? 'bg-[#FF5252]' : spendPct >= 80 ? 'bg-[#FFA502]' : 'bg-[#3FD2C0]'
                  }`}
                  style={{ width: `${spendPct}%` }}
                />
              </div>
            </div>
          )}
          <p className="text-xs text-[#84ABA6] mt-3">
            {dailySpend == null || dailyCap == null ? 'Spend budget data unavailable.' : `${spendPct}% of daily budget consumed.`}
          </p>
        </Card>
      </div>

      {/* Signature Notched Panel: Quick Action Operational Center */}
      <Panel
        notchedLabel="OPERATIONAL DESK"
        notchedIcon={<Zap className="w-3 h-3 text-[#3FD2C0]" />}
        className="mt-8"
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="p-4 rounded-2xl bg-[rgba(11,74,71,0.4)] border border-[rgba(63,210,192,0.18)] flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[#3FD2C0] mb-1">
                <CreditCard className="w-4 h-4" />
                <span>Approval Actions</span>
              </div>
              <h3 className="text-base font-bold text-[#EAF6F4] mb-1">Refund Requests</h3>
              <p className="text-xs text-[#B6D5D1] leading-relaxed">
                Staff executive review console with verified customer trust indicators and automated eligibility checks.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-4 w-full"
              rightIcon={<ArrowRight className="w-3.5 h-3.5" />}
              onClick={() => navigate('/refunds')}
            >
              Open Approval Queue
            </Button>
          </div>

          <div className="p-4 rounded-2xl bg-[rgba(11,74,71,0.4)] border border-[rgba(63,210,192,0.18)] flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[#3FD2C0] mb-1">
                <Server className="w-4 h-4" />
                <span>Explainability (R5)</span>
              </div>
              <h3 className="text-base font-bold text-[#EAF6F4] mb-1">Trace Inspector</h3>
              <p className="text-xs text-[#B6D5D1] leading-relaxed">
                Spec 14 per-turn traces: inspect routing confidence, product resolution, retrieved chunks, and grounding scores.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-4 w-full"
              rightIcon={<ArrowRight className="w-3.5 h-3.5" />}
              onClick={() => navigate('/conversations')}
            >
              View Conversations
            </Button>
          </div>

          <div className="p-4 rounded-2xl bg-[rgba(11,74,71,0.4)] border border-[rgba(63,210,192,0.18)] flex flex-col justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[#3FD2C0] mb-1">
                <Database className="w-4 h-4" />
                <span>Knowledge Freshness</span>
              </div>
              <h3 className="text-base font-bold text-[#EAF6F4] mb-1">Catalog & Policies</h3>
              <p className="text-xs text-[#B6D5D1] leading-relaxed">
                Trigger catalog sync jobs with live progress bar, draft policy versions, and run automated pre-promotion evals.
              </p>
            </div>
            <Button
              variant="primary"
              size="sm"
              className="mt-4 w-full"
              rightIcon={<ArrowRight className="w-3.5 h-3.5" />}
              onClick={() => navigate('/knowledge')}
            >
              Sync Knowledge
            </Button>
          </div>
        </div>
      </Panel>

      {/* Signature Arch Scroll Control (jump to health) */}
      <div className="flex justify-center pt-2">
        <ArchControl label="HEALTH" direction="down" onClick={scrollToHealth} />
      </div>

      {/* System Health Section (Spec 16.4 Screen 1) */}
      <div ref={healthRef} className="pt-4">
        <Panel
          notchedLabel="SYSTEM TELEMETRY"
          notchedIcon={<Activity className="w-3 h-3 text-[#3FD2C0]" />}
        >
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div className="glass-panel p-4 rounded-2xl border border-[rgba(63,210,192,0.15)] flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-[rgba(46,213,115,0.15)] border border-[rgba(46,213,115,0.4)] flex items-center justify-center text-[#2ED573] shrink-0">
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs font-bold text-[#EAF6F4]">LLM Orchestrator Gateway</p>
                <p className="text-[11px] text-[#B6D5D1]">{reports?.latency_p50_ms == null ? 'Latency unavailable' : `Latency p50: ${reports.latency_p50_ms}ms`}</p>
                <StatusBadge status={health?.status === 'healthy' ? 'success' : health ? 'danger' : 'warning'} label={health?.status || 'Unavailable'} size="sm" className="mt-1.5" />
              </div>
            </div>

            <div className="glass-panel p-4 rounded-2xl border border-[rgba(63,210,192,0.15)] flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-[rgba(46,213,115,0.15)] border border-[rgba(46,213,115,0.4)] flex items-center justify-center text-[#2ED573] shrink-0">
                <Database className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs font-bold text-[#EAF6F4]">PostgreSQL & pgvector</p>
                <p className="text-[11px] text-[#B6D5D1]">PostgreSQL dependency health</p>
                <StatusBadge status={health?.dependencies?.postgres === 'healthy' ? 'success' : health?.dependencies?.postgres ? 'danger' : 'warning'} label={health?.dependencies?.postgres || 'Unavailable'} size="sm" className="mt-1.5" />
              </div>
            </div>

            <div className="glass-panel p-4 rounded-2xl border border-[rgba(63,210,192,0.15)] flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-[rgba(46,213,115,0.15)] border border-[rgba(46,213,115,0.4)] flex items-center justify-center text-[#2ED573] shrink-0">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs font-bold text-[#EAF6F4]">Staff Auth & Session Gate</p>
                <p className="text-[11px] text-[#B6D5D1]">Redis dependency health</p>
                <StatusBadge status={health?.dependencies?.redis === 'healthy' ? 'success' : health?.dependencies?.redis ? 'danger' : 'warning'} label={health?.dependencies?.redis || 'Unavailable'} size="sm" className="mt-1.5" />
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
};
