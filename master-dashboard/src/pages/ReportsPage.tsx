import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import {
  Panel,
  Card,
  Button,
  Tabs,
} from '../components/ui';
import {
  BarChart3,
  Download,
  Coins,
} from 'lucide-react';

export const ReportsPage: React.FC = () => {
  const [days, setDays] = useState(30);
  const [exportError, setExportError] = useState(false);

  // 1. Fetch performance & deflection metrics
  const { data: metrics, isLoading: metricsLoading, isError: metricsError, refetch: refetchMetrics } = useQuery({
    queryKey: ['performanceMetrics', days],
    queryFn: async () => {
      const resp = await api.get(`/api/admin/v1/reports/metrics?days=${days}`);
      return resp.data;
    },
  });

  // 2. Fetch spend ledger reports
  const { data: spendData, isLoading: spendLoading, isError: spendError, refetch: refetchSpend } = useQuery({
    queryKey: ['spendReport'],
    queryFn: async () => {
      const resp = await api.get('/api/admin/v1/reports/spend');
      return resp.data;
    },
  });

  const dailySpend = spendData?.daily?.spent_inr;
  const dailyCap = spendData?.daily?.cap_inr;
  const dailyPct = dailySpend == null || !dailyCap ? 0 : Math.min(100, Math.round((dailySpend / dailyCap) * 100));

  const monthlySpend = spendData?.monthly?.spent_inr;
  const monthlyCap = spendData?.monthly?.cap_inr;
  const monthlyPct = monthlySpend == null || !monthlyCap ? 0 : Math.min(100, Math.round((monthlySpend / monthlyCap) * 100));

  const deflectionRatePct = metrics?.conversations?.deflection_rate_pct;
  const escalationRatePct = deflectionRatePct == null ? null : Math.round((100 - deflectionRatePct) * 10) / 10;
  const latencyP50 = metrics?.latency_ms?.p50;
  const latencyP95 = metrics?.latency_ms?.p95;
  const costPerConv = metrics?.financials?.cost_per_conversation_inr;
  const topIntents = metrics?.top_intents || [];

  const handleExportCsv = async () => {
    setExportError(false);
    try {
      const response = await api.get(`/api/admin/v1/reports/export.csv?days=${days}`, {
        responseType: 'blob',
      });
      const downloadUrl = URL.createObjectURL(response.data);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = `support-report-${days}-days.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(downloadUrl);
    } catch {
      setExportError(true);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="micro-label">SPEC 16.4 • ANALYTICS & EXPORT</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
            Operating Reports & Intelligence
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1">
            Track customer deflection rate, SLA latencies, model token economics, and download compliance audit reports.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Tabs
            tabs={[
              { id: '7', label: '7 Days' },
              { id: '30', label: '30 Days' },
              { id: '90', label: '90 Days' },
            ]}
            activeTab={String(days)}
            onChange={(val) => setDays(Number(val))}
            size="sm"
          />

          <Button
            variant="secondary"
            size="sm"
            onClick={handleExportCsv}
            leftIcon={<Download className="w-3.5 h-3.5" />}
          >
            Export CSV
          </Button>
        </div>
      </div>

      {(metricsError || spendError) && (
        <div role="alert" className="p-3 rounded-xl border border-[rgba(255,82,82,0.35)] bg-[rgba(255,82,82,0.1)] text-sm text-[#FF8585] flex flex-wrap items-center gap-3">
          <span>Some report data could not be loaded.</span>
          {metricsError && <Button size="sm" variant="secondary" onClick={() => refetchMetrics()}>Retry performance data</Button>}
          {spendError && <Button size="sm" variant="secondary" onClick={() => refetchSpend()}>Retry spend data</Button>}
        </div>
      )}

      {exportError && (
        <div role="alert" className="p-3 rounded-xl border border-[rgba(255,82,82,0.35)] bg-[rgba(255,82,82,0.1)] text-sm text-[#FF8585] flex flex-wrap items-center gap-3">
          <span>CSV export failed. Check your access and try again.</span>
          <Button size="sm" variant="secondary" onClick={handleExportCsv}>Retry export</Button>
        </div>
      )}

      {/* Spend Meters Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <Panel
          tier="data"
          notchedLabel="DAILY BUDGET METER"
          notchedIcon={<Coins className="w-3.5 h-3.5 text-[#3FD2C0]" />}
          className="space-y-3"
        >
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black font-mono text-[#EAF6F4]">
              {spendLoading ? 'Loading…' : dailySpend == null ? 'Unavailable' : `₹${dailySpend.toLocaleString('en-IN')}`}
            </span>
            <span className="text-xs text-[#84ABA6]">
              {dailyCap == null ? '' : `Cap: ₹${dailyCap.toLocaleString('en-IN')} (${dailyPct}%)`}
            </span>
          </div>

          <div className="w-full h-3 rounded-full bg-[rgba(11,74,71,0.8)] overflow-hidden border border-[rgba(63,210,192,0.2)]">
            <div
              className={`h-full transition-all duration-300 rounded-full ${
                dailyPct >= 95 ? 'bg-[#FF5252]' : dailyPct >= 80 ? 'bg-[#FFA502]' : 'bg-[#3FD2C0]'
              }`}
              style={{ width: `${dailySpend == null || dailyCap == null ? 0 : dailyPct}%` }}
            />
          </div>
          <p className="text-xs text-[#B6D5D1]">
            Daily token limit enforced under Spec 6.2 spend protection.
          </p>
        </Panel>

        <Panel
          tier="data"
          notchedLabel="MONTHLY BUDGET CEILING"
          notchedIcon={<Coins className="w-3.5 h-3.5 text-[#3FD2C0]" />}
          className="space-y-3"
        >
          <div className="flex items-baseline justify-between">
            <span className="text-2xl font-black font-mono text-[#EAF6F4]">
              {spendLoading ? 'Loading…' : monthlySpend == null ? 'Unavailable' : `₹${monthlySpend.toLocaleString('en-IN')}`}
            </span>
            <span className="text-xs text-[#84ABA6]">
              {monthlyCap == null ? '' : `Cap: ₹${monthlyCap.toLocaleString('en-IN')} (${monthlyPct}%)`}
            </span>
          </div>

          <div className="w-full h-3 rounded-full bg-[rgba(11,74,71,0.8)] overflow-hidden border border-[rgba(63,210,192,0.2)]">
            <div
              className={`h-full transition-all duration-300 rounded-full ${
                monthlyPct >= 95 ? 'bg-[#FF5252]' : monthlyPct >= 80 ? 'bg-[#FFA502]' : 'bg-[#3FD2C0]'
              }`}
              style={{ width: `${monthlySpend == null || monthlyCap == null ? 0 : monthlyPct}%` }}
            />
          </div>
          <p className="text-xs text-[#B6D5D1]">
            Monthly tenant ceiling. Overages trigger supervisor alert and cache-only fallback.
          </p>
        </Panel>
      </div>

      {/* Primary Operating Metrics 4-Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <Card variant="light" microCaption="DEFLECTION" title="Deflection Rate">
          <span className="text-3xl font-extrabold font-mono text-[#0F3D3B] block mt-1">
            {metricsLoading ? 'Loading…' : deflectionRatePct == null ? 'Unavailable' : `${deflectionRatePct}%`}
          </span>
          <span className="text-xs text-[#4A7B78] mt-2 block">
            {metrics?.conversations ? `${metrics.conversations.deflected} of ${metrics.conversations.total} conversations resolved autonomously.` : 'Conversation data unavailable.'}
          </span>
        </Card>

        <Card variant="dark" microCaption="RESPONSE TIME" title="Median Latency (p50)">
          <span className="text-3xl font-extrabold font-mono text-[#3FD2C0] block mt-1">
            {metricsLoading ? 'Loading…' : latencyP50 == null ? 'Unavailable' : `${latencyP50}ms`}
          </span>
          <span className="text-xs text-[#84ABA6] mt-2 block">
            {latencyP95 == null ? 'p95 latency unavailable.' : `p95 tail latency: ${latencyP95}ms across all channels.`}
          </span>
        </Card>

        <Card variant="dark" microCaption="UNIT ECONOMICS" title="Cost / Conversation">
          <span className="text-3xl font-extrabold font-mono text-[#EAF6F4] block mt-1">
            {metricsLoading ? 'Loading…' : costPerConv == null ? 'Unavailable' : `₹${costPerConv}`}
          </span>
          <span className="text-xs text-[#84ABA6] mt-2 block">
            Average LLM token expenditure per completed customer session.
          </span>
        </Card>

        <Card variant="dark" microCaption="ESCALATIONS" title="Escalation Rate">
          <span className="text-3xl font-extrabold font-mono text-[#FFA502] block mt-1">
            {escalationRatePct == null ? 'Unavailable' : `${escalationRatePct}%`}
          </span>
          <span className="text-xs text-[#84ABA6] mt-2 block">
            Customer inquiries requiring human supervisor intervention.
          </span>
        </Card>
      </div>

      {/* Top Intents Distribution */}
      <Panel
        tier="data"
        notchedLabel="TOP CUSTOMER INTENTS"
        notchedIcon={<BarChart3 className="w-3.5 h-3.5 text-[#3FD2C0]" />}
      >
        <div className="space-y-4">
          {topIntents.map((item: any) => (
            <div key={item.intent} className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-[#EAF6F4] font-mono capitalize">
                  {item.intent.replace(/_/g, ' ')}
                </span>
                <span className="font-mono text-[#3FD2C0]">
                  {item.count} inquiries ({item.percentage}%)
                </span>
              </div>
              <div className="w-full h-2 rounded-full bg-[rgba(11,74,71,0.6)] overflow-hidden">
                <div
                  className="h-full bg-[#3FD2C0] rounded-full transition-all duration-300"
                  style={{ width: `${item.percentage}%` }}
                />
              </div>
            </div>
          ))}
          {topIntents.length === 0 && <p className="text-sm text-[#84ABA6]">No intent report data is available for this period.</p>}
        </div>
      </Panel>
    </div>
  );
};
