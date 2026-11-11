import React, { useState } from 'react';
import { Panel, Button } from '../components/ui';
import {
  Terminal,
  Copy,
  Check,
  Search,
  MessageSquare,
  Server,
  AlertTriangle,
  Info,
  ChevronDown,
  ChevronUp,
  HelpCircle,
  CheckCircle2,
} from 'lucide-react';

interface ScriptItem {
  id: string;
  title: string;
  category: 'database' | 'evals' | 'knowledge' | 'channels' | 'docker';
  badge: string;
  safety: 'safe' | 'mutation' | 'critical';
  summary: string;
  localCmd: string;
  dockerCmd: string;
  purpose: string;
  prerequisites: string[];
  expectedOutput: string;
  importantNotes: string;
}

const SCRIPT_CATALOG: ScriptItem[] = [
  {
    id: 'seed-staff',
    title: 'Seed Staff Accounts & Roles',
    category: 'database',
    badge: 'Database & Auth',
    safety: 'mutation',
    summary: 'Idempotently bootstraps Executive, Manager, and Admin staff credentials with tenant memberships.',
    localCmd: 'python support-assistant/db/seed_staff.py',
    dockerCmd: 'docker compose exec assistant-api python db/seed_staff.py',
    purpose: 'Initializes the default staff accounts for the Master Control Dashboard. It creates Executive (executive@novaretail.com), Manager (manager@novaretail.com), and Admin (admin@novaretail.com) accounts in PostgreSQL and links them to demo-shop and tenant_novaretail.',
    prerequisites: ['PostgreSQL container running and healthy', 'DATABASE_ASYNC_URL configured in .env'],
    expectedOutput: 'Created tenant: demo-shop (NovaRetail Demo Store)\nCreated staff user: executive@novaretail.com (role: executive)\nCreated staff user: manager@novaretail.com (role: manager)\nCreated staff user: admin@novaretail.com (role: admin)\nSeeding complete.',
    importantNotes: 'This script is 100% idempotent. If accounts already exist, it will safely skip duplicates without altering existing sessions or passwords.',
  },
  {
    id: 'db-migrate',
    title: 'Apply Alembic Database Migrations',
    category: 'database',
    badge: 'Database & Schema',
    safety: 'mutation',
    summary: 'Applies all PostgreSQL schema revisions, RLS policies, indexes, and catalog tables to head.',
    localCmd: 'alembic -c support-assistant/alembic.ini upgrade head',
    dockerCmd: 'docker compose run --rm migrate',
    purpose: 'Brings the database schema up to date with the latest revisions (including pgvector HNSW indexes, RLS session policies, catalog ingestion run tracking, and audit log tables).',
    prerequisites: ['PostgreSQL container up on port 5432 with pgvector extension enabled'],
    expectedOutput: 'INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.\nINFO  [alembic.runtime.migration] Will assume transactional DDL.\nINFO  [alembic.runtime.migration] Running upgrade -> 004_catalog_ingestion_runs',
    importantNotes: 'Always run this before starting the assistant-api service or whenever pull updates introduce new schema revisions.',
  },
  {
    id: 'run-evals',
    title: 'Run Golden Benchmark Evaluations (R1–R5)',
    category: 'evals',
    badge: 'AI QA & Evals',
    safety: 'safe',
    summary: 'Executes the 10 golden benchmark scenarios verifying Tanglish, Tamil, order tracking, ₹2,000 refund gates, and injection defense.',
    localCmd: 'python support-assistant/evals/run_evals.py',
    dockerCmd: 'docker compose exec assistant-api python evals/run_evals.py',
    purpose: 'Automated verification test ensuring the LLM orchestrator and deterministic policy engine strictly adhere to NovaRetail policies R1 through R5 without regression.',
    prerequisites: ['Python 3.11 environment with dependencies installed'],
    expectedOutput: 'Running Evaluation Suite: 10 Scenarios\n[PASS] EVAL-01: Tanglish Order Tracking\n[PASS] EVAL-02: Tamil Script Order Tracking\n[PASS] EVAL-03: Look-Alike Disambiguation (Pulse Buds 141 vs 131)\n[PASS] EVAL-04: Exact Specs & Live Price Grounding\n[PASS] EVAL-05: Auto-Refund <= ₹2,000\n[PASS] EVAL-06: Refund > ₹2,000 Escalated to Supervisor\n[PASS] EVAL-07: Digital Goods Ineligible Refund Refusal\n[PASS] EVAL-08: Prompt Injection Blocked\n[PASS] EVAL-09: Admin Identity Spoofing Blocked\n[PASS] EVAL-10: Human Escalation Handoff\nResult: 10/10 Passed (100.0%)',
    importantNotes: 'Zero network calls required when running in deterministic mock mode. Safe to run at any time in CI/CD pipelines.',
  },
  {
    id: 'adversarial-tests',
    title: 'Run Adversarial Security & Red-Team Tests',
    category: 'evals',
    badge: 'Security Audit',
    safety: 'safe',
    summary: 'Runs pytest suite targeting prompt injections, jailbreaks, role spoofing, and customer identity isolation.',
    localCmd: 'pytest support-assistant/tests/test_adversarial_and_evals.py -v',
    dockerCmd: 'docker compose exec assistant-api pytest tests/test_adversarial_and_evals.py -v',
    purpose: 'Verifies that the LLM cannot be manipulated by user prompts to bypass financial caps, reveal other customer data, or execute unauthorized tool calls.',
    prerequisites: ['pytest and test dependencies installed'],
    expectedOutput: 'tests/test_adversarial_and_evals.py::test_prompt_injection_blocked PASSED\ntests/test_adversarial_and_evals.py::test_spoofed_admin_role_rejected PASSED\ntests/test_adversarial_and_evals.py::test_refund_boundary_enforcement PASSED\n=== 3 passed in 1.45s ===',
    importantNotes: 'Complies with skill-security-auditor and senior-qa-engineer standards.',
  },
  {
    id: 'verify-contrast',
    title: 'Verify WCAG 2.1 AA Color Contrast',
    category: 'evals',
    badge: 'Accessibility',
    safety: 'safe',
    summary: 'Automated script checking all 13 glassmorphic design token pairs against WCAG AA standards.',
    localCmd: 'npm --prefix master-dashboard run verify-contrast',
    dockerCmd: 'docker compose exec dashboard node scripts/verify-contrast.js',
    purpose: 'Validates that text on dark teal glass, mint surfaces, and semantic alert badges satisfies minimum 4.5:1 (normal text) and 3:1 (large text/UI elements) contrast ratios.',
    prerequisites: ['Node.js 18+ installed'],
    expectedOutput: '=== WCAG 2.1 AA Color Contrast Verification ===\n[PASS] Primary Text on Dark Teal Canvas: 15.71:1\n[PASS] Primary Text on Teal Panel: 13.06:1\n[PASS] Primary Text on Mint Surface: 10.50:1\nSUCCESS: All 13 token pairs pass WCAG 2.1 AA contrast requirements!',
    importantNotes: 'Run this whenever modifying tokens.css or color variables.',
  },
  {
    id: 'catalog-sync',
    title: 'Trigger Live Catalog Ingestion & Embedding Sync',
    category: 'knowledge',
    badge: 'Knowledge & RAG',
    safety: 'mutation',
    summary: 'Fetches products from ApexStore API, generates chunked text, computes dense embeddings, and stages draft version.',
    localCmd: 'curl -X POST http://localhost:8000/api/admin/v1/knowledge/catalog/sync -H "Content-Type: application/json"',
    dockerCmd: 'docker compose exec assistant-api curl -X POST http://localhost:8000/api/admin/v1/knowledge/catalog/sync',
    purpose: 'Updates product data, pricing, specs, and RAG knowledge vectors. Enforces a 1-active-job constraint and generates an immutable IngestionRun record.',
    prerequisites: ['APEXSTORE_CATALOG_API_URL and NVIDIA_NIM_BASE_URL (or BGE-M3 local model) configured in .env'],
    expectedOutput: '{\n  "job_id": "job_cat_20261105_01",\n  "status": "queued",\n  "message": "Catalog sync job initiated successfully."\n}',
    importantNotes: 'You can track real-time sync progress directly from the Knowledge screen or via GET /api/admin/v1/knowledge/jobs/<job_id>.',
  },
  {
    id: 'whatsapp-simulate',
    title: 'Simulate Inbound WhatsApp Customer Message',
    category: 'channels',
    badge: 'Channels & Webhooks',
    safety: 'safe',
    summary: 'Sends a simulated webhook payload to test multilingual intent routing, order tracking, and session memory.',
    localCmd: 'curl -X POST http://localhost:8000/webhooks/whatsapp -H "Content-Type: application/json" -d \'{"entry":[{"changes":[{"value":{"messages":[{"from":"+919876543210","text":{"body":"Enna order status? ORD-9912"}}]}}]}]}\'',
    dockerCmd: 'docker compose exec assistant-api curl -X POST http://localhost:8000/webhooks/whatsapp -H "Content-Type: application/json" -d \'{"entry":[{"changes":[{"value":{"messages":[{"from":"+919876543210","text":{"body":"Enna order status? ORD-9912"}}]}}]}]}\'',
    purpose: 'Simulates a WhatsApp webhook message from a customer in Tanglish or Tamil, verifying that the gateway classifies language, extracts intent, and triggers tools properly.',
    prerequisites: ['assistant-api running on port 8000'],
    expectedOutput: '{\n  "status": "delivered",\n  "response_text": "வணக்கம்! Your order ORD-9912 is currently Out for Delivery via BlueDart.",\n  "intent": "order_status"\n}',
    importantNotes: 'In production, WhatsApp requests validate the X-Hub-Signature-256 header against WHATSAPP_APP_SECRET.',
  },
  {
    id: 'docker-rebuild-all',
    title: 'Rebuild & Start Full Production Stack',
    category: 'docker',
    badge: 'Docker & Ops',
    safety: 'critical',
    summary: 'Rebuilds frontend and backend container images and boots Postgres, Redis, Assistant API, Outbox Worker, and Dashboard.',
    localCmd: 'docker compose up -d --build --remove-orphans',
    dockerCmd: 'docker compose up -d --build --remove-orphans',
    purpose: 'Full clean restart and rebuild of all services. Ensures code changes in React dashboard or FastAPI backend are compiled into fresh production containers.',
    prerequisites: ['Docker Desktop / Docker Engine running'],
    expectedOutput: 'Container customersupportproject-postgres-1  Running\nContainer customersupportproject-redis-1     Running\nContainer customersupportproject-assistant-api-1  Started\nContainer customersupportproject-dashboard-1      Started',
    importantNotes: 'PostgreSQL and Redis data are persisted in named Docker volumes (postgres_data, redis_data) and will NOT be erased.',
  },
  {
    id: 'docker-logs-api',
    title: 'Stream Backend Gateway Logs',
    category: 'docker',
    badge: 'Observability',
    safety: 'safe',
    summary: 'Live tail of assistant-api container logs, showing incoming requests, model routing, and trace correlation IDs.',
    localCmd: 'docker compose logs -f assistant-api',
    dockerCmd: 'docker compose logs -f assistant-api',
    purpose: 'Essential for debugging live API errors, inspecting LLM prompt generation, and watching correlation IDs (X-Correlation-ID) in real time.',
    prerequisites: ['assistant-api container running'],
    expectedOutput: 'INFO: 127.0.0.1:54321 - "POST /api/admin/v1/auth/login HTTP/1.1" 200 OK\n[INFO] [correlation_id=corr_881] Router classified intent: refund_request (confidence: 0.94)',
    importantNotes: 'Press Ctrl+C to exit streaming logs without affecting the running container.',
  },
];

export const ScriptsPage: React.FC = () => {
  const [activeCategory, setActiveCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [execMode, setExecMode] = useState<'local' | 'docker'>('local');
  const [expandedId, setExpandedId] = useState<string | null>('seed-staff');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Widget embed generator state
  const [widgetTenant, setWidgetTenant] = useState('tenant_novaretail');
  const [widgetApiBase, setWidgetApiBase] = useState(() => window.location.origin);
  const [widgetCopied, setWidgetCopied] = useState(false);

  const categories = [
    { id: 'all', label: 'All Runbooks', count: SCRIPT_CATALOG.length },
    { id: 'database', label: 'Database & Auth', count: SCRIPT_CATALOG.filter((s) => s.category === 'database').length },
    { id: 'evals', label: 'AI Evals & Tests', count: SCRIPT_CATALOG.filter((s) => s.category === 'evals').length },
    { id: 'knowledge', label: 'Knowledge & RAG', count: SCRIPT_CATALOG.filter((s) => s.category === 'knowledge').length },
    { id: 'channels', label: 'Channels & Widget', count: SCRIPT_CATALOG.filter((s) => s.category === 'channels').length },
    { id: 'docker', label: 'Docker & Ops', count: SCRIPT_CATALOG.filter((s) => s.category === 'docker').length },
  ];

  const filteredScripts = SCRIPT_CATALOG.filter((s) => {
    const matchesCat = activeCategory === 'all' || s.category === activeCategory;
    const q = searchQuery.toLowerCase();
    const matchesSearch =
      !q ||
      s.title.toLowerCase().includes(q) ||
      s.summary.toLowerCase().includes(q) ||
      s.localCmd.toLowerCase().includes(q) ||
      s.badge.toLowerCase().includes(q);
    return matchesCat && matchesSearch;
  });

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const normalizedWidgetApiBase = widgetApiBase.trim().replace(/\/+$/, '');
  const escapeHtmlAttribute = (value: string) => value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  const widgetSnippet = `<script
  src="${escapeHtmlAttribute(normalizedWidgetApiBase)}/widget/v1/widget.js"
  data-tenant="${escapeHtmlAttribute(widgetTenant.trim())}"
  data-api-base="${escapeHtmlAttribute(normalizedWidgetApiBase)}"
  defer>
</script>`;

  const handleCopyWidget = () => {
    navigator.clipboard.writeText(widgetSnippet);
    setWidgetCopied(true);
    setTimeout(() => setWidgetCopied(false), 2000);
  };

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 py-6 pb-28">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold uppercase tracking-widest text-[#3FD2C0]">
              SYSTEM RUNBOOKS & TOOLKIT
            </span>
            <span className="text-[10px] text-[#84ABA6]">• SPEC V2.MD OPS COMPLIANT</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-[#EAF6F4] tracking-tight">
            Developer & Operations Scripts
          </h1>
          <p className="text-sm text-[#B6D5D1] mt-1 max-w-3xl">
            Interactive reference guides, executable commands, database setup routines, and automated evaluation harnesses for operating the NovaRetail platform.
          </p>
        </div>

        {/* Environment Mode Switcher */}
        <div className="glass-chrome p-1.5 rounded-full border border-[rgba(63,210,192,0.25)] flex items-center gap-1 shrink-0 self-start md:self-auto shadow-md">
          <button
            type="button"
            onClick={() => setExecMode('local')}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
              execMode === 'local'
                ? 'bg-[#3FD2C0] text-[#062F2E] font-bold shadow-[0_2px_8px_rgba(63,210,192,0.35)]'
                : 'text-[#B6D5D1] hover:text-[#EAF6F4]'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Local Shell (Host)</span>
          </button>
          <button
            type="button"
            onClick={() => setExecMode('docker')}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
              execMode === 'docker'
                ? 'bg-[#3FD2C0] text-[#062F2E] font-bold shadow-[0_2px_8px_rgba(63,210,192,0.35)]'
                : 'text-[#B6D5D1] hover:text-[#EAF6F4]'
            }`}
          >
            <Server className="w-3.5 h-3.5" />
            <span>Docker Container</span>
          </button>
        </div>
      </div>

      {/* Filter Chips & Live Search */}
      <div className="space-y-4">
        {/* Category Pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 max-w-full">
          {categories.map((cat) => (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all cursor-pointer flex items-center gap-2 ${
                activeCategory === cat.id
                  ? 'bg-[#3FD2C0] text-[#062F2E] shadow-[0_2px_10px_rgba(63,210,192,0.35)] font-bold'
                  : 'glass-chrome text-[#B6D5D1] hover:text-[#EAF6F4] hover:border-[#3FD2C0]'
              }`}
            >
              <span>{cat.label}</span>
              <span
                className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                  activeCategory === cat.id
                    ? 'bg-[rgba(6,47,46,0.25)] text-[#062F2E]'
                    : 'bg-[rgba(11,74,71,0.6)] text-[#3FD2C0]'
                }`}
              >
                {cat.count}
              </span>
            </button>
          ))}
        </div>

        {/* Live Search Input */}
        <div className="relative">
          <Search className="absolute left-4 top-3.5 w-4 h-4 text-[#84ABA6]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search runbooks by title, command keyword, or purpose..."
            className="w-full pl-11 pr-4 py-3 rounded-2xl bg-[rgba(6,47,46,0.7)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] placeholder-[#84ABA6] text-sm focus:border-[#3FD2C0] focus:ring-2 focus:ring-[rgba(63,210,192,0.25)] outline-none transition-all shadow-inner"
          />
        </div>
      </div>

      {/* Scripts Grid / List */}
      <div className="space-y-4">
        {filteredScripts.length === 0 ? (
          <div className="glass-panel p-12 text-center rounded-3xl border border-[rgba(63,210,192,0.2)]">
            <HelpCircle className="w-12 h-12 text-[#84ABA6] mx-auto mb-3" />
            <h3 className="text-base font-bold text-[#EAF6F4]">No runbooks found</h3>
            <p className="text-xs text-[#84ABA6] mt-1">
              Try adjusting your search query or switching to another category.
            </p>
          </div>
        ) : (
          filteredScripts.map((script) => {
            const isExpanded = expandedId === script.id;
            const activeCmd = execMode === 'local' ? script.localCmd : script.dockerCmd;
            const isCopied = copiedId === script.id;

            return (
              <div
                key={script.id}
                className="glass-panel rounded-3xl border border-[rgba(63,210,192,0.25)] hover:border-[rgba(63,210,192,0.45)] transition-all overflow-hidden shadow-lg"
              >
                {/* Header Row */}
                <div className="p-5 sm:p-6 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <div className="space-y-1.5 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[rgba(63,210,192,0.15)] text-[#3FD2C0] uppercase tracking-wider font-mono">
                        {script.badge}
                      </span>
                      {script.safety === 'safe' && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[rgba(63,210,192,0.1)] text-[#3FD2C0] font-semibold flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Safe / Read-Only
                        </span>
                      )}
                      {script.safety === 'mutation' && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[rgba(255,165,2,0.15)] text-[#FFA502] font-semibold flex items-center gap-1">
                          <Info className="w-3 h-3" /> Data Modification
                        </span>
                      )}
                      {script.safety === 'critical' && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[rgba(255,82,82,0.15)] text-[#FF8585] font-semibold flex items-center gap-1">
                          <AlertTriangle className="w-3 h-3" /> Stack Rebuild
                        </span>
                      )}
                    </div>
                    <h3 className="text-lg font-bold text-[#EAF6F4] tracking-tight">
                      {script.title}
                    </h3>
                    <p className="text-xs text-[#B6D5D1] leading-relaxed max-w-3xl">
                      {script.summary}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 self-start lg:self-auto shrink-0">
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => handleCopy(activeCmd, script.id)}
                      leftIcon={isCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                    >
                      {isCopied ? 'Copied!' : 'Copy Command'}
                    </Button>
                    <button
                      type="button"
                      onClick={() => setExpandedId(isExpanded ? null : script.id)}
                      className="glass-chrome p-2 rounded-full border border-[rgba(63,210,192,0.25)] text-[#84ABA6] hover:text-[#3FD2C0] hover:border-[#3FD2C0] transition-colors cursor-pointer"
                      title={isExpanded ? 'Collapse instructions' : 'Expand instructions'}
                    >
                      {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                {/* Command Bar */}
                <div className="px-5 sm:px-6 pb-4">
                  <div className="p-3.5 rounded-2xl bg-[rgba(4,30,29,0.85)] border border-[rgba(63,210,192,0.2)] font-mono text-xs text-[#3FD2C0] flex items-center justify-between gap-3 overflow-x-auto shadow-inner">
                    <div className="flex items-center gap-2.5 truncate">
                      <span className="text-[#84ABA6] select-none">$</span>
                      <span className="truncate">{activeCmd}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleCopy(activeCmd, script.id)}
                      className="p-1.5 rounded-lg hover:bg-[rgba(63,210,192,0.15)] text-[#84ABA6] hover:text-[#3FD2C0] transition-colors shrink-0 cursor-pointer"
                      title="Copy to clipboard"
                    >
                      {isCopied ? <Check className="w-3.5 h-3.5 text-[#3FD2C0]" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                </div>

                {/* Expandable Deep Documentation Drawer */}
                {isExpanded && (
                  <div className="px-5 sm:px-6 py-5 bg-[rgba(6,47,46,0.5)] border-t border-[rgba(63,210,192,0.15)] space-y-4 text-xs animate-fadeIn">
                    <div>
                      <h4 className="font-bold text-[#EAF6F4] uppercase tracking-wider text-[11px] mb-1">
                        Purpose & Operational Context
                      </h4>
                      <p className="text-[#B6D5D1] leading-relaxed">
                        {script.purpose}
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Prerequisites */}
                      <div className="p-3.5 rounded-xl bg-[rgba(11,74,71,0.4)] border border-[rgba(63,210,192,0.15)]">
                        <span className="font-bold text-[#3FD2C0] uppercase tracking-wider text-[10px] block mb-1.5">
                          Prerequisites
                        </span>
                        <ul className="space-y-1 text-[#B6D5D1]">
                          {script.prerequisites.map((p, idx) => (
                            <li key={idx} className="flex items-start gap-1.5">
                              <span className="text-[#3FD2C0]">•</span>
                              <span>{p}</span>
                            </li>
                          ))}
                        </ul>
                      </div>

                      {/* Important Notes */}
                      <div className="p-3.5 rounded-xl bg-[rgba(11,74,71,0.4)] border border-[rgba(63,210,192,0.15)]">
                        <span className="font-bold text-[#3FD2C0] uppercase tracking-wider text-[10px] block mb-1.5">
                          Safety Guardrail / Note
                        </span>
                        <p className="text-[#B6D5D1] leading-relaxed">
                          {script.importantNotes}
                        </p>
                      </div>
                    </div>

                    {/* Expected Output */}
                    <div>
                      <span className="font-bold text-[#EAF6F4] uppercase tracking-wider text-[11px] block mb-1.5">
                        Expected Terminal Output Sample
                      </span>
                      <pre className="p-3.5 rounded-xl bg-[rgba(4,30,29,0.9)] border border-[rgba(63,210,192,0.15)] font-mono text-[11px] text-[#A2C7C3] overflow-x-auto whitespace-pre leading-relaxed shadow-inner">
                        {script.expectedOutput}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Interactive Web Widget Snippet Generator */}
      <Panel notchedLabel="INTEGRATION TOOLS" className="mt-10">
        <div className="space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-lg font-bold text-[#EAF6F4] flex items-center gap-2">
                <MessageSquare className="w-5 h-5 text-[#3FD2C0]" />
                Customer Web Chat Widget Embed Snippet
              </h3>
              <p className="text-xs text-[#B6D5D1] mt-0.5">
                Embed the floating trilingual support chat on any frontend storefront (React, Shopify, WooCommerce, or plain HTML).
              </p>
            </div>

            <Button
              size="sm"
              variant="primary"
              onClick={handleCopyWidget}
              leftIcon={widgetCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            >
              {widgetCopied ? 'Copied HTML!' : 'Copy Script Tag'}
            </Button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#3FD2C0] mb-1.5">
                Tenant Identifier
              </label>
              <input
                type="text"
                value={widgetTenant}
                onChange={(e) => setWidgetTenant(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl bg-[rgba(6,47,46,0.7)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] font-mono text-xs outline-none focus:border-[#3FD2C0]"
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#3FD2C0] mb-1.5">
                Assistant API Base URL
              </label>
              <input
                type="url"
                value={widgetApiBase}
                onChange={(e) => setWidgetApiBase(e.target.value)}
                placeholder="https://support-api.example.com"
                className="w-full px-3.5 py-2.5 rounded-xl bg-[rgba(6,47,46,0.7)] border border-[rgba(63,210,192,0.25)] text-[#EAF6F4] font-mono text-xs outline-none focus:border-[#3FD2C0]"
              />
              <p className="mt-1.5 text-[11px] text-[#84ABA6]">
                For a live store, use the public HTTPS URL of your assistant API and allow the storefront domain in WIDGET_ALLOWED_ORIGINS.
              </p>
            </div>
          </div>

          <pre className="p-4 rounded-2xl bg-[rgba(4,30,29,0.9)] border border-[rgba(63,210,192,0.2)] font-mono text-xs text-[#3FD2C0] overflow-x-auto shadow-inner leading-relaxed">
            {widgetSnippet}
          </pre>
        </div>
      </Panel>
    </div>
  );
};
