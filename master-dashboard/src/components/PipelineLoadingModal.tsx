import React, { useState, useEffect } from 'react';
import {
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Database,
  Cpu,
  Layers,
  ShieldCheck,
  DownloadCloud,
  ChevronDown,
  ChevronUp,
  X,
  XCircle,
  ExternalLink,
  Terminal,
  Clock,
  Sparkles,
} from 'lucide-react';
import { Button } from './ui/Button';
import { StatusBadge } from './ui/StatusBadge';
import { IngestionJob } from '../types/schemas';

export interface PipelineLoadingModalProps {
  isOpen: boolean;
  onClose: () => void;
  job: IngestionJob | null;
  onViewRegistry?: () => void;
  onRetryFailed?: (jobId: string) => void;
  isRetrying?: boolean;
  onCancelPipeline?: (jobId: string) => void;
  isCancelling?: boolean;
}

interface PipelineStage {
  id: string;
  stepNumber: number;
  title: string;
  description: string;
  icon: React.ReactNode;
  minProgress: number;
}

const PIPELINE_STAGES: PipelineStage[] = [
  {
    id: 'source',
    stepNumber: 1,
    title: 'Source Extraction',
    description: 'Streaming catalog records from the configured store API with rate-limiting.',
    icon: <DownloadCloud className="w-4 h-4" />,
    minProgress: 5,
  },
  {
    id: 'normalize',
    stepNumber: 2,
    title: 'Normalization & Specs',
    description: 'Validating product taxonomies, price currency, and technical specifications.',
    icon: <Layers className="w-4 h-4" />,
    minProgress: 25,
  },
  {
    id: 'embed',
    stepNumber: 3,
    title: 'Neural & Hybrid Embedding',
    description: 'Generating 1024-dim dense vectors with BGE-M3 / Resilient Local Embedder.',
    icon: <Cpu className="w-4 h-4" />,
    minProgress: 50,
  },
  {
    id: 'index',
    stepNumber: 4,
    title: 'Pgvector HNSW Indexing',
    description: 'Content hashing, transactional chunk upserts, and PostgreSQL RLS tenant binding.',
    icon: <Database className="w-4 h-4" />,
    minProgress: 75,
  },
  {
    id: 'eval',
    stepNumber: 5,
    title: 'Pre-Promotion Eval Gate',
    description: 'Automated deterministic smoke testing and cross-product isolation checks.',
    icon: <ShieldCheck className="w-4 h-4" />,
    minProgress: 95,
  },
];

export const PipelineLoadingModal: React.FC<PipelineLoadingModalProps> = ({
  isOpen,
  onClose,
  job,
  onViewRegistry,
  onRetryFailed,
  isRetrying = false,
  onCancelPipeline,
  isCancelling = false,
}) => {
  const [isMinimized, setIsMinimized] = useState(false);
  const [showLogs, setShowLogs] = useState(true);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  // Auto-maximize when modal opens
  useEffect(() => {
    if (isOpen) {
      setIsMinimized(false);
      setShowCancelConfirm(false);
    }
  }, [isOpen]);

  if (!isOpen || !job) return null;

  const pct = Math.min(100, Math.max(0, job.progress_pct || 0));
  const isFinished = ['succeeded', 'completed', 'failed', 'cancelled'].includes(job.status);
  const isSuccess = ['succeeded', 'completed'].includes(job.status);
  const isFailed = job.status === 'failed';
  const isCancelled = job.status === 'cancelled';
  const isRunning = ['queued', 'running'].includes(job.status);

  // Compute status for each stage
  const getStageStatus = (stage: PipelineStage): 'completed' | 'active' | 'pending' | 'failed' => {
    if (isSuccess) return 'completed';
    if ((isFailed || isCancelled) && pct < stage.minProgress) return 'pending';
    if (isFailed && pct >= stage.minProgress && pct < stage.minProgress + 20) return 'failed';
    if (isCancelled && pct >= stage.minProgress && pct < stage.minProgress + 20) return 'failed';
    if (pct >= stage.minProgress + 20) return 'completed';
    if (pct >= stage.minProgress) return 'active';
    return 'pending';
  };

  // Minimized Floating Pill Bar (Staff can continue browsing while pipeline runs)
  if (isMinimized) {
    return (
      <div
        role="region"
        aria-label="Active Knowledge Ingestion Pipeline Status"
        className="fixed bottom-6 right-6 z-50 animate-in slide-in-from-bottom-5 duration-300"
      >
        <div className="flex items-center gap-4 px-5 py-3 rounded-full glass-panel border border-[#3FD2C0] shadow-[0_12px_40px_rgba(6,47,46,0.85)]">
          <div className="flex items-center gap-2.5">
            {isRunning ? (
              <RefreshCw className="w-4 h-4 text-[#3FD2C0] animate-spin" />
            ) : isSuccess ? (
              <CheckCircle2 className="w-4 h-4 text-[#2ED573]" />
            ) : isCancelled ? (
              <AlertTriangle className="w-4 h-4 text-[#FFA502]" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-[#FF8585]" />
            )}
            <div>
              <p className="text-xs font-bold text-[#EAF6F4] flex items-center gap-1.5">
                <span>Ingestion Pipeline #{job.job_id.slice(-6)}</span>
                <span className="font-mono text-[#3FD2C0]">({pct}%)</span>
              </p>
              <p className="text-[10px] text-[#84ABA6]">
                {job.stats?.chunks_indexed || 0} chunks indexed • {job.status.toUpperCase()}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 pl-2 border-l border-[rgba(255,255,255,0.1)]">
            {isRunning && onCancelPipeline && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onCancelPipeline(job.job_id);
                }}
                disabled={isCancelling}
                className="p-1.5 rounded-full hover:bg-[rgba(255,82,82,0.2)] text-[#FF8585] transition-colors"
                title="Cancel Pipeline"
                aria-label="Cancel Pipeline"
              >
                <XCircle className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={() => setIsMinimized(false)}
              className="p-1.5 rounded-full hover:bg-[rgba(63,210,192,0.15)] text-[#3FD2C0] transition-colors"
              title="Expand Pipeline View"
              aria-label="Expand Pipeline View"
            >
              <ChevronUp className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-full hover:bg-[rgba(255,255,255,0.1)] text-[#B6D5D1] transition-colors"
              title="Close"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="pipeline-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
    >
      {/* Blurred Deep Teal Backdrop */}
      <div
        className="fixed inset-0 bg-[#062F2E]/80 backdrop-blur-md transition-opacity duration-300"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Main Glass Panel */}
      <div className="relative w-full max-w-4xl max-h-[92vh] flex flex-col rounded-3xl glass-panel border border-[rgba(232,242,240,0.2)] shadow-[0_24px_80px_rgba(6,47,46,0.9)] overflow-hidden animate-in zoom-in-95 duration-200">
        
        {/* Top Header Notch Tab */}
        <div className="p-5 sm:p-6 pb-4 border-b border-[rgba(232,242,240,0.12)] flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-[rgba(63,210,192,0.15)] border border-[rgba(63,210,192,0.3)] flex items-center justify-center text-[#3FD2C0]">
              <Sparkles className="w-5 h-5 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="micro-label">SPEC 5.3 & 16.6 • RAG CATALOG SYNC</span>
                <StatusBadge
                  status={
                    isSuccess ? 'success' : isFailed ? 'danger' : isCancelled ? 'warning' : 'info'
                  }
                  label={job.status.toUpperCase()}
                />
              </div>
              <h2
                id="pipeline-modal-title"
                className="text-xl sm:text-2xl font-extrabold text-[#EAF6F4] tracking-tight mt-0.5"
              >
                {isSuccess
                  ? 'Catalog Ingestion Succeeded'
                  : isFailed
                  ? 'Catalog Ingestion Failed'
                  : isCancelled
                  ? 'Catalog Ingestion Cancelled'
                  : 'Knowledge Ingestion Pipeline'}
              </h2>
            </div>
          </div>

          {/* Window controls */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsMinimized(true)}
              className="p-2 rounded-xl bg-[rgba(11,74,71,0.6)] hover:bg-[rgba(63,210,192,0.2)] text-[#B6D5D1] hover:text-[#3FD2C0] transition-colors"
              title="Minimize to Floating Bar"
              aria-label="Minimize Pipeline Modal"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-xl bg-[rgba(11,74,71,0.6)] hover:bg-[rgba(255,255,255,0.15)] text-[#B6D5D1] hover:text-white transition-colors"
              title="Close Modal"
              aria-label="Close Pipeline Modal"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Scrollable Content Body */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-6">
          
          {/* Main Progress Bar & Counter Card */}
          <div className="p-5 rounded-2xl glass-data border border-[rgba(63,210,192,0.25)] space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {isRunning ? (
                  <RefreshCw className="w-5 h-5 text-[#3FD2C0] animate-spin" />
                ) : isSuccess ? (
                  <CheckCircle2 className="w-5 h-5 text-[#2ED573]" />
                ) : (
                  <AlertTriangle className="w-5 h-5 text-[#FF8585]" />
                )}
                <span className="font-bold text-[#EAF6F4] text-base">
                  {isRunning
                    ? pct < 25
                      ? 'Extracting catalog products from store API...'
                      : pct < 50
                      ? 'Validating schemas and normalizing technical specifications...'
                      : pct < 75
                      ? 'Generating 1024-dim dense embeddings & cosine projections...'
                      : pct < 95
                      ? 'Upserting pgvector HNSW chunks and linking version draft...'
                      : 'Executing pre-promotion smoke and product isolation evals...'
                    : isSuccess
                    ? 'Catalog ingestion and indexing completed successfully!'
                    : 'Ingestion pipeline halted. See error log details below.'}
                </span>
              </div>
              <span className="text-2xl font-black font-mono text-[#3FD2C0]">
                {pct}%
              </span>
            </div>

            {/* Glowing Fluid Progress Bar */}
            <div className="w-full h-3 rounded-full bg-[rgba(6,47,46,0.9)] overflow-hidden border border-[rgba(63,210,192,0.3)] relative">
              <div
                className={`h-full transition-all duration-500 rounded-full ${
                  isFailed
                    ? 'bg-[#FF5252]'
                    : isSuccess
                    ? 'bg-[#2ED573]'
                    : 'bg-gradient-to-r from-[#17A58F] via-[#3FD2C0] to-[#E8F2F0] animate-pulse'
                }`}
                style={{ width: `${Math.max(4, pct)}%` }}
              />
            </div>

            {/* Live Telemetry Metric Badges */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 pt-1">
              <div className="p-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(232,242,240,0.08)]">
                <p className="text-[10px] uppercase font-bold text-[#84ABA6]">Products</p>
                <p className="text-base font-extrabold text-[#EAF6F4] font-mono mt-0.5">
                  {job.stats?.products_processed || 0} / {job.stats?.products_seen || 0}
                </p>
              </div>

              <div className="p-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(232,242,240,0.08)]">
                <p className="text-[10px] uppercase font-bold text-[#84ABA6]">Chunks Indexed</p>
                <p className="text-base font-extrabold text-[#3FD2C0] font-mono mt-0.5">
                  {job.stats?.chunks_indexed || 0}
                </p>
              </div>

              <div className="p-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(232,242,240,0.08)]">
                <p className="text-[10px] uppercase font-bold text-[#84ABA6]">Added / Updated</p>
                <p className="text-base font-extrabold text-[#2ED573] font-mono mt-0.5">
                  +{job.stats?.added || 0} / ~{job.stats?.updated || 0}
                </p>
              </div>

              <div className="p-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(232,242,240,0.08)]">
                <p className="text-[10px] uppercase font-bold text-[#84ABA6]">Failed Items</p>
                <p className={`text-base font-extrabold font-mono mt-0.5 ${(job.stats?.failed || 0) > 0 ? 'text-[#FF8585]' : 'text-[#EAF6F4]'}`}>
                  {job.stats?.failed || 0}
                </p>
              </div>

              <div className="p-2.5 rounded-xl bg-[rgba(11,74,71,0.5)] border border-[rgba(232,242,240,0.08)]">
                <p className="text-[10px] uppercase font-bold text-[#84ABA6]">Duration</p>
                <p className="text-base font-extrabold text-[#EAF6F4] font-mono mt-0.5 flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5 text-[#84ABA6]" />
                  <span>{job.stats?.duration_seconds ? `${job.stats.duration_seconds}s` : 'Active'}</span>
                </p>
              </div>
            </div>
          </div>

          {/* Stepper Flow: 5 Architectural Pipeline Stages */}
          <div className="space-y-3">
            <p className="micro-label">PIPELINE EXECUTION STAGES</p>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
              {PIPELINE_STAGES.map((stage) => {
                const status = getStageStatus(stage);
                return (
                  <div
                    key={stage.id}
                    className={`p-3.5 rounded-2xl border transition-all duration-300 relative flex flex-col justify-between ${
                      status === 'active'
                        ? 'bg-[rgba(63,210,192,0.12)] border-[#3FD2C0] shadow-[0_0_20px_rgba(63,210,192,0.2)]'
                        : status === 'completed'
                        ? 'bg-[rgba(46,213,115,0.08)] border-[rgba(46,213,115,0.35)]'
                        : status === 'failed'
                        ? 'bg-[rgba(255,82,82,0.1)] border-[rgba(255,82,82,0.4)]'
                        : 'bg-[rgba(11,74,71,0.3)] border-[rgba(232,242,240,0.08)] opacity-60'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <div
                          className={`w-7 h-7 rounded-xl flex items-center justify-center ${
                            status === 'active'
                              ? 'bg-[#3FD2C0] text-[#062F2E]'
                              : status === 'completed'
                              ? 'bg-[#2ED573] text-[#062F2E]'
                              : status === 'failed'
                              ? 'bg-[#FF5252] text-white'
                              : 'bg-[rgba(232,242,240,0.1)] text-[#B6D5D1]'
                          }`}
                        >
                          {status === 'active' ? (
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          ) : status === 'completed' ? (
                            <CheckCircle2 className="w-3.5 h-3.5" />
                          ) : status === 'failed' ? (
                            <AlertTriangle className="w-3.5 h-3.5" />
                          ) : (
                            stage.icon
                          )}
                        </div>

                        <span className="text-[10px] font-mono font-bold text-[#84ABA6]">
                          0{stage.stepNumber}
                        </span>
                      </div>

                      <h4 className="text-xs font-bold text-[#EAF6F4] leading-snug">
                        {stage.title}
                      </h4>
                      <p className="text-[11px] text-[#84ABA6] mt-1 line-clamp-3 leading-relaxed">
                        {stage.description}
                      </p>
                    </div>

                    <div className="mt-3 pt-2 border-t border-[rgba(255,255,255,0.06)] flex items-center justify-between">
                      <span
                        className={`text-[9px] font-black uppercase tracking-wider ${
                          status === 'active'
                            ? 'text-[#3FD2C0]'
                            : status === 'completed'
                            ? 'text-[#2ED573]'
                            : status === 'failed'
                            ? 'text-[#FF8585]'
                            : 'text-[#84ABA6]'
                        }`}
                      >
                        {status === 'active'
                          ? 'In Progress'
                          : status === 'completed'
                          ? 'Completed'
                          : status === 'failed'
                          ? 'Error'
                          : 'Pending'}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Cancelled Banner */}
          {isCancelled && (
            <div className="p-4 rounded-2xl bg-[rgba(255,165,2,0.12)] border border-[rgba(255,165,2,0.35)] text-[#FFA502] text-xs flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-bold">Pipeline Cancelled by Staff:</p>
                <p className="leading-relaxed">
                  {job.error_message || 'The ingestion pipeline was safely halted by staff. Active knowledge index and previous versions remain untouched.'}
                </p>
              </div>
            </div>
          )}

          {/* Error Banner if Pipeline Failed */}
          {isFailed && job.error_message && (
            <div className="p-4 rounded-2xl bg-[rgba(255,82,82,0.12)] border border-[rgba(255,82,82,0.35)] text-[#FF8585] text-xs flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-bold">Pipeline Issue Detected:</p>
                <p className="leading-relaxed">{job.error_message}</p>
              </div>
            </div>
          )}

          {/* Terminal Event Console */}
          <div className="rounded-2xl glass-data border border-[rgba(232,242,240,0.12)] overflow-hidden">
            <div className="px-4 py-2.5 bg-[rgba(6,47,46,0.95)] border-b border-[rgba(232,242,240,0.08)] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Terminal className="w-3.5 h-3.5 text-[#3FD2C0]" />
                <span className="text-xs font-bold text-[#EAF6F4]">Pipeline Execution Logs</span>
                <span className="font-mono text-[10px] text-[#84ABA6]">Job #{job.job_id}</span>
              </div>
              <button
                onClick={() => setShowLogs(!showLogs)}
                className="text-[11px] text-[#84ABA6] hover:text-[#3FD2C0] transition-colors"
              >
                {showLogs ? 'Hide Logs' : 'Show Logs'}
              </button>
            </div>

            {showLogs && (
              <div className="p-4 bg-[rgba(3,25,24,0.85)] max-h-48 overflow-y-auto font-mono text-[11px] text-[#B6D5D1] space-y-1.5">
                <p className="text-[#84ABA6]">
                  [{new Date().toLocaleTimeString('en-IN')}] Job initialized with ID {job.job_id}
                </p>
                {pct >= 20 && (
                  <p className="text-[#3FD2C0]">
                    [{new Date().toLocaleTimeString('en-IN')}] source_fetch_completed: Streamed {job.stats?.products_seen ?? 0} products from the configured store API
                  </p>
                )}
                {pct >= 50 && (
                  <p className="text-[#EAF6F4]">
                    [{new Date().toLocaleTimeString('en-IN')}] specifications_normalized: Extracted technical attributes, unit metrics, and warranty terms
                  </p>
                )}
                {pct >= 75 && (
                  <p className="text-[#3FD2C0]">
                    [{new Date().toLocaleTimeString('en-IN')}] embeddings_generated: 1024-dim dense vectors projected via Resilient Embedder
                  </p>
                )}
                {pct >= 90 && (
                  <p className="text-[#EAF6F4]">
                    [{new Date().toLocaleTimeString('en-IN')}] hnsw_indexed: Indexed {job.stats?.chunks_indexed || 21} chunks into knowledge_chunks and linked version
                  </p>
                )}
                {isSuccess && (
                  <p className="text-[#2ED573] font-bold">
                    [{new Date().toLocaleTimeString('en-IN')}] pipeline_succeeded: Draft version staged with {job.stats?.chunks_indexed || 21} chunks in {job.stats?.duration_seconds || '0.54'}s
                  </p>
                )}
                {isFailed && (
                  <p className="text-[#FF8585] font-bold">
                    [{new Date().toLocaleTimeString('en-IN')}] pipeline_failed: {job.error_message || 'Ingestion halted'}
                  </p>
                )}
                {isCancelled && (
                  <p className="text-[#FFA502] font-bold">
                    [{new Date().toLocaleTimeString('en-IN')}] pipeline_cancelled: Pipeline halted by staff. Active knowledge index preserved.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-4 sm:p-5 border-t border-[rgba(232,242,240,0.12)] bg-[rgba(6,47,46,0.6)] flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs text-[#84ABA6]">
            <span>Spec 16.6 Knowledge Synchronization</span>
            <span>•</span>
            <span className="font-mono">{job.tenant_id}</span>
          </div>

          <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
            {/* Cancel Pipeline Action */}
            {isRunning && onCancelPipeline && (
              <div className="flex items-center gap-2">
                {showCancelConfirm ? (
                  <div className="flex items-center gap-2 p-1.5 bg-[rgba(255,82,82,0.15)] border border-[rgba(255,82,82,0.35)] rounded-2xl">
                    <span className="text-[11px] font-bold text-[#FF8585] px-2">
                      Abort sync?
                    </span>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => {
                        setShowCancelConfirm(false);
                        onCancelPipeline(job.job_id);
                      }}
                      disabled={isCancelling}
                      isLoading={isCancelling}
                    >
                      Yes, Cancel
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowCancelConfirm(false)}
                      disabled={isCancelling}
                    >
                      Keep Running
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => setShowCancelConfirm(true)}
                    disabled={isCancelling}
                    isLoading={isCancelling}
                    leftIcon={<XCircle className="w-3.5 h-3.5" />}
                  >
                    Cancel Pipeline
                  </Button>
                )}
              </div>
            )}

            {isSuccess && onViewRegistry && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  onClose();
                  onViewRegistry();
                }}
                leftIcon={<ExternalLink className="w-3.5 h-3.5" />}
              >
                Inspect in Version Registry
              </Button>
            )}

            {isFailed && onRetryFailed && (job.stats?.failed || 0) > 0 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onRetryFailed(job.job_id)}
                disabled={isRetrying}
                isLoading={isRetrying}
                leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
              >
                Retry Failed Items ({job.stats?.failed})
              </Button>
            )}

            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
            >
              {isFinished ? 'Close Window' : 'Run in Background'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
