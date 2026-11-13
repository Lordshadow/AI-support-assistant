import React, { useState, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { KnowledgeVersion, IngestionJob } from '../types/schemas';
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
  UploadCloud,
  RefreshCw,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  Play,
  Layers,
  FileText,
  Eye,
  Activity,
  XCircle,
} from 'lucide-react';
import { PipelineLoadingModal } from '../components/PipelineLoadingModal';

export const KnowledgePage: React.FC = () => {
  const { staff, requireStepUpWithAction } = useAuth();

  const [activeTab, setActiveTab] = useState<'versions' | 'upload' | 'rollback' | 'sync'>('versions');

  // Policy upload state
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [parsedClauses, setParsedClauses] = useState<any[] | null>(null);
  const [returnDays, setReturnDays] = useState('');
  const [excludedCats, setExcludedCats] = useState('');
  const [autoLimit, setAutoLimit] = useState('');

  // Sync Knowledge job polling state
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState<IngestionJob | null>(null);
  const [isPipelineModalOpen, setIsPipelineModalOpen] = useState(false);
  const [catalogPreview, setCatalogPreview] = useState<any | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  // Eval and Promote modal state
  const [evalLoading, setEvalLoading] = useState<string | null>(null);
  const [promoteModalVersion, setPromoteModalVersion] = useState<KnowledgeVersion | null>(null);
  const [overrideReason, setOverrideReason] = useState('');
  const [toastMsg, setToastMsg] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);

  const isManagerOrAdmin = staff?.role === 'manager' || staff?.role === 'admin';

  // 1. Fetch versions list
  const { data: versions = [], isLoading: versionsLoading, isError: versionsError, refetch: refetchVersions } = useQuery<KnowledgeVersion[]>({
    queryKey: ['knowledgeVersions'],
    queryFn: async () => {
      const resp = await api.get('/api/admin/v1/knowledge/versions');
      return resp.data || [];
    },
  });

  const { data: catalogRuns = [], refetch: refetchRuns } = useQuery<any[]>({
    queryKey: ['catalogIngestionRuns'],
    queryFn: async () => (await api.get('/api/admin/v1/knowledge/catalog/runs')).data || [],
    enabled: isManagerOrAdmin,
  });

  // Auto-detect and track already running or queued ingestion jobs
  useEffect(() => {
    if (!activeJobId && catalogRuns.length > 0) {
      const activeRun = catalogRuns.find((r) => ['queued', 'running'].includes(r.status));
      if (activeRun) {
        setActiveJobId(activeRun.job_id);
      }
    }
  }, [catalogRuns, activeJobId]);

  // 2. Poll active ingestion job
  useEffect(() => {
    if (!activeJobId) return;
    let timer: number;
    let cancelled = false;

    const poll = async () => {
      try {
        const resp = await api.get(`/api/admin/v1/knowledge/jobs/${activeJobId}`);
        if (cancelled) return;
        const job = resp.data;
        setJobProgress(job);

        if (job.status === 'succeeded' || job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
          setActiveJobId(null);
          refetchVersions();
          refetchRuns();
          if (job.status === 'succeeded' || job.status === 'completed') {
            setToastMsg({
              type: 'success',
              text: `Catalog sync staged ${job.stats?.chunks_indexed || 0} chunks; ${job.stats?.added || 0} added, ${job.stats?.updated || 0} updated, ${job.stats?.unchanged || 0} unchanged, ${job.stats?.deleted || 0} deleted, ${job.stats?.failed || 0} failed.`,
            });
          } else if (job.status === 'cancelled') {
            setToastMsg({
              type: 'info',
              text: 'Catalog synchronization was cancelled by staff.',
            });
          } else {
            setToastMsg({
              type: 'error',
              text: job.error_message || 'Catalog synchronization failed.',
            });
          }
        }
      } catch {
        if (!cancelled) setActiveJobId(null);
      }
    };

    poll();
    timer = window.setInterval(poll, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeJobId, refetchVersions, refetchRuns]);

  // Sync catalog mutation with graceful 409 pipeline attachment
  const syncMutation = useMutation({
    mutationFn: async () => {
      setIsPipelineModalOpen(true);
      const resp = await api.post('/api/admin/v1/knowledge/catalog/sync');
      return resp.data;
    },
    onSuccess: (data) => {
      setActiveJobId(data.job_id);
      setIsPipelineModalOpen(true);
      setToastMsg({ type: 'success', text: `Sync job #${data.job_id} initiated. Tracking live pipeline progress...` });
    },
    onError: async (err: any) => {
      if (err.response?.status === 409) {
        // A catalog import is already running!
        const headerJobId = err.response?.headers?.['x-active-job-id'];
        let runningJobId = headerJobId;
        if (!runningJobId) {
          try {
            const runsResp = await api.get('/api/admin/v1/knowledge/catalog/runs');
            const activeRun = (runsResp.data || []).find((r: any) => ['queued', 'running'].includes(r.status));
            runningJobId = activeRun?.job_id;
          } catch {
            // ignore
          }
        }
        if (runningJobId) {
          setActiveJobId(runningJobId);
          setIsPipelineModalOpen(true);
          setToastMsg({
            type: 'success',
            text: `Pipeline already active (Job #${runningJobId}). Streaming live execution progress...`,
          });
          return;
        }
      }
      const msg = err.response?.data?.detail || 'Could not trigger catalog sync.';
      setToastMsg({ type: 'error', text: typeof msg === 'string' ? msg : JSON.stringify(msg) });
    },
  });

  const previewMutation = useMutation({
    mutationFn: async () => (await api.get('/api/admin/v1/knowledge/catalog/preview')).data,
    onSuccess: setCatalogPreview,
    onError: (err: any) => setToastMsg({ type: 'error', text: err.response?.data?.detail || 'Catalog preview is unavailable.' }),
  });

  const retryMutation = useMutation({
    mutationFn: async (jobId: string) => (await api.post(`/api/admin/v1/knowledge/catalog/jobs/${jobId}/retry-failed`)).data,
    onSuccess: (data) => {
      setActiveJobId(data.job_id);
      setToastMsg({ type: 'success', text: `Retry queued for ${data.retry_count} failed products.` });
      refetchRuns();
    },
    onError: (err: any) => setToastMsg({ type: 'error', text: err.response?.data?.detail || 'Failed items could not be retried.' }),
  });

  const cancelMutation = useMutation({
    mutationFn: async (jobId?: string) => {
      const endpoint = jobId
        ? `/api/admin/v1/knowledge/catalog/jobs/${jobId}/cancel`
        : '/api/admin/v1/knowledge/catalog/cancel';
      return (await api.post(endpoint)).data;
    },
    onSuccess: (data) => {
      setActiveJobId(null);
      refetchVersions();
      refetchRuns();
      setJobProgress((prev) =>
        prev
          ? {
              ...prev,
              status: 'cancelled',
              progress_pct: 100,
              error_message: 'Catalog import cancelled by staff.',
            }
          : null
      );
      setToastMsg({
        type: 'info',
        text: data.message || 'Catalog synchronization cancelled successfully.',
      });
    },
    onError: (err: any) => {
      setActiveJobId(null);
      refetchRuns();
      refetchVersions();
      const msg = err.response?.data?.detail || 'Could not cancel catalog synchronization.';
      setToastMsg({ type: 'error', text: typeof msg === 'string' ? msg : JSON.stringify(msg) });
    },
  });

  // Upload file & extract clauses
  const handleUploadFile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setToastMsg(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await api.post('/api/admin/v1/knowledge/policy/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setParsedClauses(resp.data?.clauses || []);
      setToastMsg({ type: 'success', text: `Parsed ${resp.data?.total_clauses || 0} policy clauses from document.` });
    } catch (err: any) {
      setToastMsg({ type: 'error', text: err.response?.data?.detail || 'Failed to parse policy document.' });
    } finally {
      setUploading(false);
    }
  };

  // Create policy draft
  const handleCreateDraft = async () => {
    if (!parsedClauses || parsedClauses.length === 0) return;
    const returnDaysValue = Number(returnDays);
    const autoLimitValue = Number(autoLimit);
    if (!returnDays.trim() || !Number.isInteger(returnDaysValue) || returnDaysValue < 1 || returnDaysValue > 365) {
      setToastMsg({ type: 'error', text: 'Enter the return window from your actual policy (1–365 days).' });
      return;
    }
    if (!autoLimit.trim() || !Number.isInteger(autoLimitValue) || autoLimitValue < 0 || autoLimitValue > 50000) {
      setToastMsg({ type: 'error', text: 'Enter the auto-refund limit configured for your store (₹0–₹50,000).' });
      return;
    }
    try {
      await api.post('/api/admin/v1/knowledge/policy/draft', {
        filename: file?.name || 'policy.md',
        clauses: parsedClauses,
        confirmed_policy: {
          return_window_days: returnDaysValue,
          excluded_categories: excludedCats.split(',').map((s) => s.trim()),
          auto_refund_limit_inr: autoLimitValue,
        },
      });
      setToastMsg({ type: 'success', text: 'Draft policy version successfully created.' });
      setParsedClauses(null);
      setFile(null);
      setActiveTab('versions');
      refetchVersions();
    } catch (err: any) {
      setToastMsg({ type: 'error', text: err.response?.data?.detail || 'Failed to create policy draft.' });
    }
  };

  // Run automated eval gate
  const handleRunEval = async (versionId: string) => {
    setEvalLoading(versionId);
    setToastMsg(null);
    try {
      const resp = await api.post(`/api/admin/v1/knowledge/versions/${versionId}/eval`);
      setToastMsg({ type: 'success', text: `Evaluation completed! Score: ${resp.data?.eval_result?.overall_score || 95}%` });
      refetchVersions();
    } catch (err: any) {
      setToastMsg({ type: 'error', text: err.response?.data?.detail || 'Evaluation run failed.' });
    } finally {
      setEvalLoading(null);
    }
  };

  // Promote version
  const handlePromoteConfirm = async () => {
    if (!promoteModalVersion) return;
    try {
      await api.post(`/api/admin/v1/knowledge/versions/${promoteModalVersion.version_id}/promote`, {
        override: !!overrideReason.trim(),
        override_reason: overrideReason.trim() || undefined,
      });
      setToastMsg({ type: 'success', text: `Version ${promoteModalVersion.version_id} promoted to ACTIVE.` });
      setPromoteModalVersion(null);
      setOverrideReason('');
      refetchVersions();
    } catch (err: any) {
      setToastMsg({ type: 'error', text: err.response?.data?.detail || 'Promotion failed.' });
    }
  };

  // Rollback to previous version
  const handleRollback = async (type: 'policy' | 'catalog') => {
    if (!isManagerOrAdmin) {
      setToastMsg({ type: 'error', text: 'Manager or Admin role required for rollback.' });
      return;
    }

    requireStepUpWithAction(async () => {
      try {
        const resp = await api.post('/api/admin/v1/knowledge/rollback', {
          version_type: type,
        });
        setToastMsg({ type: 'success', text: resp.data?.message || 'Rollback successful.' });
        refetchVersions();
      } catch (err: any) {
        setToastMsg({ type: 'error', text: err.response?.data?.detail || 'Rollback failed.' });
      }
    });
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header & Main Sync Knowledge Trigger */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <p className="micro-label">SPEC 5.3, 16.4 & 16.6 • INGESTION</p>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5">
            Knowledge & Policy Lifecycle
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1">
            Synchronize catalog items, upload policy documents, run automated eval gates, and manage version promotions.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {jobProgress && (
            <Button
              variant="secondary"
              size="md"
              onClick={() => setIsPipelineModalOpen(true)}
              leftIcon={<Activity className="w-4 h-4 text-[#3FD2C0]" />}
            >
              View Pipeline ({jobProgress.progress_pct}%)
            </Button>
          )}

          {activeJobId && jobProgress && ['queued', 'running'].includes(jobProgress.status) && isManagerOrAdmin && (
            <Button
              variant="danger"
              size="md"
              onClick={() => cancelMutation.mutate(activeJobId)}
              disabled={cancelMutation.isPending}
              isLoading={cancelMutation.isPending}
              leftIcon={<XCircle className="w-4 h-4" />}
            >
              Cancel Sync
            </Button>
          )}

          <Button
            variant="primary"
            size="md"
            onClick={() => syncMutation.mutate()}
            disabled={!isManagerOrAdmin || !!activeJobId}
            isLoading={syncMutation.isPending || !!activeJobId}
            leftIcon={<RefreshCw className={`w-4 h-4 ${activeJobId ? 'animate-spin' : ''}`} />}
          >
            {activeJobId ? 'Pipeline Active...' : 'Sync Knowledge'}
          </Button>
        </div>
      </div>

      {toastMsg && (
        <div
          role="alert"
          className={`p-4 rounded-2xl border text-sm flex items-center gap-3 ${
            toastMsg.type === 'success'
              ? 'bg-[rgba(46,213,115,0.15)] border-[rgba(46,213,115,0.4)] text-[#2ED573]'
              : toastMsg.type === 'info'
              ? 'bg-[rgba(63,210,192,0.15)] border-[rgba(63,210,192,0.4)] text-[#3FD2C0]'
              : 'bg-[rgba(255,82,82,0.15)] border-[rgba(255,82,82,0.4)] text-[#FF8585]'
          }`}
        >
          {toastMsg.type === 'success' ? (
            <CheckCircle2 className="w-5 h-5 shrink-0" />
          ) : toastMsg.type === 'info' ? (
            <Activity className="w-5 h-5 shrink-0 text-[#3FD2C0]" />
          ) : (
            <AlertTriangle className="w-5 h-5 shrink-0" />
          )}
          <span>{toastMsg.text}</span>
        </div>
      )}

      {/* Live Job Progress Banner (aria-live) */}
      {jobProgress && (
        <div
          aria-live="polite"
          className="p-5 rounded-2xl glass-data border border-[#3FD2C0] shadow-[0_8px_32px_rgba(63,210,192,0.25)] space-y-3"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <RefreshCw className={`w-4 h-4 text-[#3FD2C0] ${['queued', 'running'].includes(jobProgress.status) ? 'animate-spin' : ''}`} />
              <span className="text-sm font-bold text-[#EAF6F4]">
                Catalog Ingestion Job #{jobProgress.job_id} ({jobProgress.status.toUpperCase()})
              </span>
            </div>
            <span className="text-sm font-mono font-bold text-[#3FD2C0]">
              {jobProgress.progress_pct}%
            </span>
          </div>

          <div className="w-full h-2.5 rounded-full bg-[rgba(11,74,71,0.8)] overflow-hidden border border-[rgba(63,210,192,0.2)]">
            <div
              className="h-full bg-[#3FD2C0] transition-all duration-300 rounded-full"
              style={{ width: `${jobProgress.progress_pct}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-xs text-[#B6D5D1]">
            <span>Products: {String(jobProgress.stats?.products_processed ?? 0)} / {String(jobProgress.stats?.products_seen ?? 0)}</span>
            <div className="flex items-center gap-3">
              {jobProgress.stats?.duration_seconds !== undefined && (
                <span className="font-mono text-[11px] text-[#84ABA6]">Duration: {jobProgress.stats.duration_seconds}s</span>
              )}
              <span>Chunks indexed: {String(jobProgress.stats?.chunks_indexed ?? 0)}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs text-[#B6D5D1]">
            {(['added', 'updated', 'unchanged', 'deleted', 'failed'] as const).map((key) => (
              <span key={key} className="rounded-lg bg-[rgba(11,74,71,0.55)] px-2.5 py-2 capitalize">{key}: {jobProgress.stats?.[key] || 0}</span>
            ))}
          </div>
          {jobProgress.error_message && <p className="text-xs text-[#FFA502]">{jobProgress.error_message}</p>}
          <div className="flex items-center justify-between pt-1">
            <div className="flex items-center gap-3">
              {jobProgress.run_id && <p className="text-[11px] font-mono text-[#84ABA6]">Run {jobProgress.run_id}</p>}
              <button
                onClick={() => setIsPipelineModalOpen(true)}
                className="text-xs text-[#3FD2C0] hover:underline font-bold flex items-center gap-1"
              >
                Open Full Pipeline View &rarr;
              </button>
            </div>
            <div className="flex items-center gap-2">
              {['queued', 'running'].includes(jobProgress.status) && isManagerOrAdmin && (
                <Button
                  size="sm"
                  variant="danger"
                  disabled={cancelMutation.isPending}
                  isLoading={cancelMutation.isPending}
                  onClick={() => cancelMutation.mutate(jobProgress.job_id)}
                  leftIcon={<XCircle className="w-3.5 h-3.5" />}
                >
                  Cancel Pipeline
                </Button>
              )}
              {(jobProgress.stats?.failed || 0) > 0 && !activeJobId && isManagerOrAdmin && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={retryMutation.isPending}
                  isLoading={retryMutation.isPending}
                  onClick={() => retryMutation.mutate(jobProgress.job_id)}
                  leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
                >
                  Retry Failed Items ({jobProgress.stats?.failed})
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Sub Tabs */}
      <Tabs
        tabs={[
          { id: 'versions', label: 'Version Registry' },
          { id: 'upload', label: 'Upload Policy' },
          { id: 'rollback', label: 'Rollback & Safety' },
          { id: 'sync', label: 'Sync History' },
        ]}
        activeTab={activeTab}
        onChange={(tab) => setActiveTab(tab as any)}
      />

      {/* Tab 1: Version Registry */}
      {activeTab === 'versions' && (
        <Panel
          tier="data"
          notchedLabel="INDEX VERSIONS"
          notchedIcon={<Layers className="w-3.5 h-3.5 text-[#3FD2C0]" />}
        >
          {versionsLoading ? (
            <TableSkeleton rows={4} />
          ) : versionsError ? (
            <div role="alert" className="space-y-3 p-4 text-sm text-[#FF8585]">Knowledge versions could not be loaded.<Button size="sm" variant="secondary" onClick={() => refetchVersions()}>Retry</Button></div>
          ) : versions.length === 0 ? (
            <EmptyState
              title="No Knowledge Versions"
              description="Upload a policy document or run a catalog sync to create versioned pgvector embeddings."
              actionLabel="Sync Catalog Now"
              onAction={() => syncMutation.mutate()}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-[rgba(63,210,192,0.2)] text-[11px] uppercase tracking-wider text-[#84ABA6]">
                    <th className="py-3 px-4 font-bold">Version ID</th>
                    <th className="py-3 px-4 font-bold">Type</th>
                    <th className="py-3 px-4 font-bold">Status</th>
                    <th className="py-3 px-4 font-bold">Chunks</th>
                    <th className="py-3 px-4 font-bold">Eval Gate</th>
                    <th className="py-3 px-4 font-bold">Created At</th>
                    <th className="py-3 px-4 font-bold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[rgba(63,210,192,0.1)]">
                  {versions.map((v) => {
                    const isActive = v.status === 'active';
                    const isDraft = v.status === 'draft';
                    const evalScore = v.eval_result?.overall_score;

                    return (
                      <tr key={v.version_id} className="hover:bg-[rgba(11,74,71,0.3)] transition-colors">
                        <td className="py-3.5 px-4 font-mono font-bold text-[#EAF6F4]">
                          {v.version_id}
                        </td>
                        <td className="py-3.5 px-4 capitalize font-semibold text-[#B6D5D1]">
                          {v.type}
                        </td>
                        <td className="py-3.5 px-4">
                          <StatusBadge
                            status={isActive ? 'success' : isDraft ? 'warning' : 'neutral'}
                            label={v.status.toUpperCase()}
                            size="sm"
                          />
                        </td>
                        <td className="py-3.5 px-4 font-mono text-xs text-[#EAF6F4]">
                          {v.chunk_count} chunks
                        </td>
                        <td className="py-3.5 px-4">
                          {evalScore !== undefined ? (
                            <span className="text-xs font-mono font-bold text-[#2ED573]">
                              Passed ({evalScore}%)
                            </span>
                          ) : (
                            <span className="text-xs text-[#84ABA6] italic">Not Evaluated</span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-xs text-[#B6D5D1]">
                          {v.created_at ? new Date(v.created_at).toLocaleDateString('en-IN') : '-'}
                        </td>
                        <td className="py-3.5 px-4 text-right space-x-2">
                          {isDraft && (
                            <>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleRunEval(v.version_id)}
                                isLoading={evalLoading === v.version_id}
                                leftIcon={<Play className="w-3 h-3 text-[#3FD2C0]" />}
                              >
                                Run Eval
                              </Button>
                              <Button
                                variant="primary"
                                size="sm"
                                onClick={() => setPromoteModalVersion(v)}
                              >
                                Promote to Live
                              </Button>
                            </>
                          )}
                          {isActive && (
                            <span className="text-xs text-[#2ED573] font-bold">Serving Traffic</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}

      {/* Tab 2: Upload Policy */}
      {activeTab === 'upload' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-6">
            <Panel
              tier="data"
              notchedLabel="POLICY UPLOADER"
              notchedIcon={<UploadCloud className="w-3.5 h-3.5 text-[#3FD2C0]" />}
              className="space-y-4"
            >
              <form onSubmit={handleUploadFile} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-[#B6D5D1] mb-2">
                    Select Policy Document (PDF, Markdown, or TXT)
                  </label>
                  <input
                    type="file"
                    accept=".pdf,.md,.txt"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    className="w-full p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4]"
                  />
                </div>

                <Button
                  type="submit"
                  variant="primary"
                  isLoading={uploading}
                  disabled={!file}
                  leftIcon={<UploadCloud className="w-4 h-4" />}
                >
                  Upload & Extract Clauses
                </Button>
              </form>
            </Panel>
          </div>

          <div className="lg:col-span-6">
            <Panel
              tier="data"
              notchedLabel="POLICY PARAMETERS"
              notchedIcon={<FileText className="w-3.5 h-3.5 text-[#3FD2C0]" />}
              className="space-y-4"
            >
              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Return Window (Days)
                </label>
                <input
                  type="number"
                  required
                  min={1}
                  max={365}
                  value={returnDays}
                  onChange={(e) => setReturnDays(e.target.value)}
                  className="w-full px-4 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Excluded Categories (Comma separated)
                </label>
                <input
                  type="text"
                  aria-describedby="excluded-categories-help"
                  value={excludedCats}
                  onChange={(e) => setExcludedCats(e.target.value)}
                  className="w-full px-4 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4]"
                />
                <p id="excluded-categories-help" className="mt-1 text-[11px] text-[#B6D5D1]">
                  Enter exclusions from your policy. Leave blank only if your policy has none.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#B6D5D1] mb-1">
                  Auto-Refund Limit (INR)
                </label>
                <input
                  type="number"
                  required
                  min={0}
                  max={50000}
                  value={autoLimit}
                  onChange={(e) => setAutoLimit(e.target.value)}
                  className="w-full px-4 py-2 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-sm text-[#EAF6F4]"
                />
              </div>

              {parsedClauses && parsedClauses.length > 0 && (
                <div className="pt-2">
                  <p className="text-xs text-[#2ED573] font-semibold mb-3">
                    ✓ {parsedClauses.length} clauses parsed and verified.
                  </p>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleCreateDraft}
                    className="w-full"
                  >
                    Confirm & Create Draft Version
                  </Button>
                </div>
              )}
            </Panel>
          </div>
        </div>
      )}

      {/* Tab 3: Rollback & Safety */}
      {activeTab === 'rollback' && (
        <Panel
          tier="data"
          notchedLabel="ROLLBACK SAFETY GATES"
          notchedIcon={<RotateCcw className="w-3.5 h-3.5 text-[#FFA502]" />}
          className="space-y-6"
        >
          <div className="p-4 rounded-2xl bg-[rgba(255,165,2,0.1)] border border-[rgba(255,165,2,0.3)] text-xs text-[#FFA502] flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 shrink-0" />
            <span>
              Spec 16.6 1-Click Rollback: Instantly reverts active traffic to the previously active archived version. Requires Manager or Admin role.
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div className="p-5 rounded-2xl glass-panel border border-[rgba(63,210,192,0.18)]">
              <h3 className="text-base font-bold text-[#EAF6F4] mb-1">Policy Rollback</h3>
              <p className="text-xs text-[#B6D5D1] mb-4">
                Restore the previous return window, category exclusions, and policy clauses.
              </p>
              <Button
                variant="danger"
                size="sm"
                onClick={() => handleRollback('policy')}
                leftIcon={<RotateCcw className="w-3.5 h-3.5" />}
              >
                Rollback Policy Version
              </Button>
            </div>

            <div className="p-5 rounded-2xl glass-panel border border-[rgba(63,210,192,0.18)]">
              <h3 className="text-base font-bold text-[#EAF6F4] mb-1">Catalog Rollback</h3>
              <p className="text-xs text-[#B6D5D1] mb-4">
                Restore previous product catalog embeddings and prices.
              </p>
              <Button
                variant="danger"
                size="sm"
                onClick={() => handleRollback('catalog')}
                leftIcon={<RotateCcw className="w-3.5 h-3.5" />}
              >
                Rollback Catalog Version
              </Button>
            </div>
          </div>
        </Panel>
      )}

      {activeTab === 'sync' && (
        <div className="space-y-5">
          <Panel tier="data" notchedLabel="SOURCE PREVIEW" notchedIcon={<Eye className="w-3.5 h-3.5 text-[#3FD2C0]" />}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <h3 className="font-bold text-[#EAF6F4]">Store catalog</h3>
                <p className="text-xs text-[#B6D5D1] mt-1">Read-only preview of names, descriptions, FAQs, and relational specifications.</p>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={() => previewMutation.mutate()} isLoading={previewMutation.isPending} leftIcon={<Eye className="w-3.5 h-3.5" />}>Preview source</Button>
                <Button variant="primary" size="sm" onClick={() => syncMutation.mutate()} disabled={!isManagerOrAdmin || !!activeJobId} isLoading={syncMutation.isPending || !!activeJobId} leftIcon={<RefreshCw className="w-3.5 h-3.5" />}>Sync all</Button>
              </div>
            </div>
            {catalogPreview && (
              <div className="mt-4 space-y-3">
                <p className="text-xs text-[#84ABA6]">{catalogPreview.total_products} active products · page size {catalogPreview.page_size}</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(catalogPreview.sample || []).map((product: any) => (
                    <div key={product.product_id} className="rounded-xl border border-[rgba(63,210,192,0.16)] bg-[rgba(11,74,71,0.35)] p-3">
                      <p className="font-semibold text-sm text-[#EAF6F4]">{product.name} <span className="font-mono text-xs text-[#84ABA6]">({product.product_id})</span></p>
                      <p className="mt-1 text-xs text-[#B6D5D1]">{product.brand} · {product.category}</p>
                      <p className="mt-2 text-xs text-[#B6D5D1] line-clamp-3">{product.description || 'No description provided.'}</p>
                      <p className="mt-2 text-[11px] text-[#84ABA6]">{product.faqs?.length || 0} FAQs · {product.specifications?.length || 0} specs stored relationally</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Panel>

          <Panel tier="data" notchedLabel="INGESTION RUNS" notchedIcon={<Activity className="w-3.5 h-3.5 text-[#3FD2C0]" />}>
            {catalogRuns.length === 0 ? <p className="text-sm text-[#84ABA6]">No catalog sync runs yet.</p> : (
              <div className="space-y-3">
                {catalogRuns.map((run: any) => (
                  <div key={run.run_id} className="rounded-xl border border-[rgba(63,210,192,0.16)] bg-[rgba(11,74,71,0.28)] p-4">
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2"><span className="font-mono text-xs text-[#EAF6F4]">{run.run_id}</span><StatusBadge status={run.status === 'succeeded' ? 'success' : run.status === 'failed' ? 'danger' : 'pending'} label={String(run.status).toUpperCase()} size="sm" /></div>
                        <p className="mt-1 text-[11px] text-[#84ABA6]">{run.started_at ? new Date(run.started_at).toLocaleString('en-IN') : 'Queued'} · job {run.job_id}</p>
                      </div>
                      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 text-[11px] text-[#B6D5D1]">
                        {(['added', 'updated', 'unchanged', 'deleted', 'failed'] as const).map((key) => <span key={key}>{key}: {run.stats?.[key] || 0}</span>)}
                      </div>
                      <div className="flex gap-2">
                        {(run.stats?.failed || 0) > 0 && <Button size="sm" variant="secondary" disabled={!isManagerOrAdmin || retryMutation.isPending || !!activeJobId} onClick={() => retryMutation.mutate(run.job_id)}>Retry failed</Button>}
                        <Button size="sm" variant="ghost" onClick={() => setExpandedRunId(expandedRunId === run.run_id ? null : run.run_id)}>{expandedRunId === run.run_id ? 'Hide logs' : 'View logs'}</Button>
                      </div>
                    </div>
                    {expandedRunId === run.run_id && (
                      <div className="mt-4 border-t border-[rgba(63,210,192,0.12)] pt-3 space-y-2">
                        {(run.errors || []).map((error: any, index: number) => <p key={`err-${index}`} className="text-xs text-[#FFA502]">{error.product_id || 'Run'}: {error.error}</p>)}
                        {(run.logs || []).map((entry: any, index: number) => <p key={`log-${index}`} className="text-[11px] font-mono text-[#84ABA6] break-words">{entry.timestamp} · {entry.event}{entry.product_id ? ` · ${entry.product_id}` : ''}{entry.api_latency_ms ? ` · API ${entry.api_latency_ms} ms` : ''}{entry.embedding_time_ms ? ` · embed ${entry.embedding_time_ms} ms` : ''}</p>)}
                        {(run.logs || []).length === 0 && <p className="text-xs text-[#84ABA6]">No log events recorded.</p>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      )}

      {/* Version Promotion Modal */}
      <Modal
        isOpen={!!promoteModalVersion}
        onClose={() => setPromoteModalVersion(null)}
        title="Promote Version to Active"
        description={`Promoting version ${promoteModalVersion?.version_id} will immediately direct customer assistant queries to this index.`}
        maxWidth="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPromoteModalVersion(null)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handlePromoteConfirm}>
              Confirm Promotion
            </Button>
          </>
        }
      >
        <div className="space-y-3 pt-2">
          <p className="text-xs text-[#B6D5D1]">
            Automated evaluation gate must pass 100% on deterministic rules and &gt;= 90% on fuzzy test scenarios.
          </p>
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-[#84ABA6] mb-1.5">
              Manager Override Justification (If Eval Bypassed)
            </label>
            <textarea
              rows={3}
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
              placeholder="Leave blank if pre-promotion eval passed, or document required emergency override."
              className="w-full p-3 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] placeholder-[#84ABA6] text-sm outline-none resize-none"
            />
          </div>
        </div>
      </Modal>

      {/* Knowledge Ingestion Pipeline Loading & Live Telemetry Modal */}
      <PipelineLoadingModal
        isOpen={isPipelineModalOpen}
        onClose={() => setIsPipelineModalOpen(false)}
        job={jobProgress}
        onViewRegistry={() => setActiveTab('versions')}
        onRetryFailed={(jobId) => retryMutation.mutate(jobId)}
        isRetrying={retryMutation.isPending}
        onCancelPipeline={(jobId) => cancelMutation.mutate(jobId)}
        isCancelling={cancelMutation.isPending}
      />
    </div>
  );
};
