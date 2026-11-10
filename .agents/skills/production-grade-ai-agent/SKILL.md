---
name: production-grade-ai-agent
description: >-
  Architectural patterns, observability standards, state machine durability, evaluation-driven development,
  and human-in-the-loop governance for production-grade AI agent systems and support desks.
  Use when designing, auditing, or implementing agent backends, trace viewers, approval workflows, or knowledge sync systems.
---

# Production-Grade AI Agent Skill

## Purpose & Scope
This skill codifies the architectural standards, observability requirements, and governance patterns required to transition AI agent prototypes into mission-critical, enterprise-grade production systems. It ensures strict deterministic safety boundaries around probabilistic model operations.

---

## 1. Foundational Architecture & Safety Boundaries

### 1.1 The Deterministic Execution Membrane
- **Untrusted Output Principle:** Treat all LLM outputs (structured or unstructured) as untrusted user input.
- **Strict Schema Enforcement:** Pass all LLM arguments through rigid validation schemas (e.g., Pydantic v2 / Zod). If validation fails, trigger explicit retries or fallback to deterministic code paths rather than guessing.
- **Identity Isolation:** The AI agent must **never** determine or mutate caller identity (`customer_id`, role, tenant). Caller identity is injected as a read-only, tamper-proof `SessionContext` verified before the model runs.
- **Tool Level Scope Guards:** Every tool call enforces authorization levels (`anonymous`, `identified`, `verified`, `staff`). Financial actions (e.g., refund initiation) strictly require verified OTP session context and idempotency keys.

### 1.2 State Stratification & Durability
- **Ephemera / Working Context:** In-memory, dynamically pruned context window with token budget enforcement.
- **Semantic Store:** Vector database (pgvector) with versioned embeddings, metadata filtering (tenant, version, status).
- **Durable Checkpoints:** Relational persistence (PostgreSQL) tracking every state transition, tool call, and decision. If a worker crashes mid-trajectory, execution can resume or cleanly rollback.

---

## 2. Deep Observability & Trajectory Tracing (Spec 14 / R5)
Application-level logging is insufficient; production agents require trajectory-level telemetry.

### 2.1 Per-Turn Trace Schema
Every turn must log verifiable evidence (not subjective model rationalizations):
- **Customer Turn:** Original message, normalized message, detected language.
- **Routing Decision:** Chosen path (`cache`, `template`, `small_model`, `large_model`) with router confidence score.
- **Intent & Entities:** Classified intent, confidence score, resolved entity IDs (e.g., `product_id`).
- **Auth Context:** Trust level (`anonymous`, `identified`, `verified`), verification method (`jwt`, `whatsapp_number`, `otp`), session ID.
- **Knowledge Retrieval:** Chunk IDs, similarity scores, document titles, document/index versions.
- **Tool Execution:** Tool name, sanitized arguments (identity & PII masked), raw tool execution result, execution latency.
- **Grounding Verification:** Grounding checker result (`grounded`, `unsupported`, `contradicted`), citation mappings.
- **Resource Economics:** Prompt tokens, completion tokens, latency (ms), cost calculation (USD/INR), prompt template version.
- **Final Output:** Delivered response text, response format, timestamp.

### 2.2 Privacy & Masking (DPDP Act Compliance)
- Mask sensitive customer PII (full phone numbers, email prefixes, payment details) by default in all logs and dashboard views.
- Provide role-gated "Reveal PII" functionality with mandatory logging into `audit_events`.

---

## 3. Human-In-The-Loop (HITL) Governance & Approval Queues
- **Risk-Tiered Routing:** Low-risk, read-only inquiries resolve autonomously; high-risk actions (e.g., refunds above configurable thresholds, account overrides) trigger HITL approval states.
- **Self-Approval Prevention:** A staff member must **never** be permitted to approve an action they initiated or requested.
- **Mandatory Rationale & Audit Logging:** Approvals and rejections strictly require a recorded note/reason and write an immutable event to `audit_events` with staff ID, timestamp, and action metadata.
- **Idempotency Guarantee:** Upstream API triggers (e.g., payment gateway refund requests) must only fire once upon formal staff approval using a cryptographically unique idempotency key.

---

## 4. Evaluation-Driven Development & Continuous Improvement
- **Evaluation Triad:**
  1. *Correctness & Grounding:* Answer accurately reflects retrieved source chunks without hallucination.
  2. *Efficiency & Cost:* Trajectory completed within minimal tool steps and budgeted token limits.
  3. *Safety & Guardrails:* Zero prompt injection vulnerabilities, no unauthorized data leakages.
- **Versioned Policy Synchronization:** Knowledge ingestion must embed against draft versions, execute automated regression evals, and only promote to live upon eval pass. One-click rollback must be available.
