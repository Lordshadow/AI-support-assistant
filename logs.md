# Development Audit Log (`logs.md`)

> **Project:** Customer Support Assistant (NovaRetail)  
> **Repository:** `E:\Customer support project`  
> **Guiding Principle:** *"The LLM understands and phrases. Code decides and acts."*  
> **Logging Protocol:** Enforced by `.agents/skills/task-logger/SKILL.md`

---

## [Task-00] - Initialization, Specification Analysis & Prompt Engineering Baseline
**Timestamp:** 2026-11-02 16:21:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Initialize the development lifecycle for the Customer Support Assistant based on the application specification.
- Analyze requirements R1–R5 (English/Tamil/Tanglish support, order & refund handling, ₹2,000 refund human approval gate, ₹50,000 budget with 10× festival spike protection, and explainability/audit traces).
- Establish the prompt architecture, MCP tool schemas, initial evaluation suite, Git repository, and `task-logger` skill.

### Architectural Boundaries & Modularity
- Enforced strict separation between LLM capabilities and deterministic security/business rules.
- Defined immutable `SessionContext` injected at the transport level to prevent the LLM from ever receiving or controlling `customer_id` or authorization levels.
- Created decoupled prompt definitions and isolated evaluation harnesses.

### Files Touched
- `.gitignore` (Created - Excludes `__pycache__`, virtual environments, and nested `SkillOpt/` git repo)
- `.agents/skills/task-logger/SKILL.md` (Created - Standardization protocol for recording progress in `logs.md`)
- `support-assistant/prompts/orchestrator_system_prompt.md` (Created - Main customer support instructions, Tanglish/Tamil rules, look-alike resolution, anti-hallucination)
- `support-assistant/prompts/router_prompt.md` (Created - Ultra-fast JSON router for intent classification and model tiering)
- `support-assistant/prompts/grounding_verifier_prompt.md` (Created - Pre-transmission hallucination and policy compliance gate)
- `support-assistant/core/mcp_tool_definitions.py` (Created - OpenAI/Groq function schemas and dataclasses for MCP servers)
- `support-assistant/evals/test_eval_scenarios.json` (Created - 10 golden benchmark scenarios covering R1–R5, look-alikes, and injections)
- `support-assistant/evals/run_evals.py` (Created - Automated evaluation runner script)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/evals/run_evals.py`
- **Result:** **10/10 Scenarios Passed (100.0%)**
  - `EVAL-01` (Tanglish Order Tracking): PASS
  - `EVAL-02` (Tamil Script Order Tracking): PASS
  - `EVAL-03` (Look-Alike Disambiguation - Pulse Buds 141 vs 131): PASS
  - `EVAL-04` (Exact Product Specs & Live Price Grounding): PASS
  - `EVAL-05` (Auto-Refund <= ₹2,000): PASS
  - `EVAL-06` (Refund > ₹2,000 Escalated to Supervisor Approval): PASS
  - `EVAL-07` (Digital Goods Ineligible Refund Refusal): PASS
  - `EVAL-08` (Prompt Injection Blocked): PASS
  - `EVAL-09` (Admin Identity Spoofing Blocked): PASS
  - `EVAL-10` (Human Escalation Handoff): PASS

### Git Version Control
- **Action:** Initialized Git repository and staged baseline files.
- **Commit:** `feat(setup): initialize git repo, task-logger skill, prompts, and evaluation baseline`

---

## Modular Task Roadmap

1. **[Task-01] Core Domain Models & Ports (`support-assistant/core/`)**
   - Pure domain models (`Order`, `Product`, `RefundRequest`, `SessionContext`).
   - Abstract interfaces (`CatalogPort`, `OrderPort`, `RefundPort`, `ChannelPort`).
   - Deterministic policy logic: ₹2,000 auto-limit, 30-day return window, digital item policy, idempotency key generation.
2. **[Task-02] MockShop Adapters (`support-assistant/adapters/mockshop/`)**
   - Independent implementations of `CatalogPort`, `OrderPort`, and `RefundPort`.
   - Seed data with look-alike pairs (*Pulse Buds 141* vs *131*), order history, and refund processing.
3. **[Task-03] FastMCP Tool Servers (`support-assistant/services/mcp_servers/`)**
   - Catalog server, Order server, Refund server, and Handoff server.
   - Header-based session context injection for identity isolation.
4. **[Task-04] Fast Router, Cache & Normalizer (`support-assistant/core/router/`)**
   - Multilingual text normalizer (Tanglish/Tamil/English).
   - Redis/in-memory cache-aside with fine-grained TTLs.
   - Fixed-wording template responder for order status and greetings.
5. **[Task-05] Orchestrator & Tool Caller (`support-assistant/services/worker/`)**
   - Pipeline orchestrator with Groq API integration and mock LLM test runner.
   - Parallel tool dispatch and look-alike disambiguation logic.
6. **[Task-06] Grounding Verifier & Audit Tracing (`support-assistant/core/tracing/`)**
   - Pre-transmission grounding checks.
   - Per-turn trace recording with DPDP-compliant PII masking.
7. **[Task-07] Gateway & Channel Webhook Service (`support-assistant/services/assistant_api/`)**
   - FastAPI gateway for Web widget and WhatsApp webhooks with signature verification.
   - JWT validation and OTP step-up challenge engine.
8. **[Task-08] Comprehensive Pytest & Adversarial Suite (`support-assistant/evals/`)**
   - Automated test suite validating all policy edges, rate limits, and red-team attacks.
9. **[Task-09] Support Desk Staff Backend (`support-assistant/services/support_desk/`)**
   - Approval queue API (Approve/Reject refunds with notes).
   - "Why this answer" conversation viewer.
10. **[Task-10] Containerization & Production Packaging**
    - Docker Compose for assistant-api, worker, MCP servers, Redis, and Postgres.

---

## [Task-01] - Core Domain Models, Abstract Ports & Deterministic Policy Engine
**Timestamp:** 2026-11-02 16:30:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Establish the foundational domain models and abstract ports (`typing.Protocol`) for the application following Hexagonal Architecture (Ports and Adapters).
- Implement the core principle: *"The LLM understands and phrases. Code decides and acts."* Enforce critical business rules (₹2,000 auto-refund threshold, 30-day physical return window, non-refundable digital goods, and auth level checks) deterministically in Python so that prompts and LLM hallucinations cannot alter financial or identity boundaries.

### Architectural Boundaries & Modularity
- `core/models.py`: Completely pure Python dataclasses and Enums (`SessionContext`, `Order`, `OrderItem`, `RefundResult`, `AuthLevel`). Zero framework or vendor dependencies.
- `core/ports.py`: Decoupled `Protocol` interfaces (`CatalogPort`, `OrderPort`, `RefundPort`, `ChannelPort`, `SpeechPort`) defining exact contracts required by the core.
- `core/policy_engine.py`: Isolated rule engine with deterministic functions: `require_level()`, `verify_order_ownership()`, `check_refund_eligibility()`, `evaluate_refund_state()`, and `generate_idempotency_key()`.

### Files Touched
- `support-assistant/core/models.py` (Created - Core domain entities, session context, auth hierarchy, and domain exceptions)
- `support-assistant/core/ports.py` (Created - Abstract ports for Catalog, Orders, Refunds, Channels, and Speech)
- `support-assistant/core/policy_engine.py` (Created - Deterministic eligibility, refund state transition, and auth verification)
- `support-assistant/core/__init__.py` (Created - Clean public API exports for `core`)
- `support-assistant/tests/test_core_policy.py` (Created - Comprehensive unit test suite for core models and policies)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_core_policy.py`
- **Result:** **11/11 Unit Tests Passed (100.0% in 0.002s)**
  - `test_auth_level_hierarchy`: Verified `VERIFIED > IDENTIFIED > ANONYMOUS` ordering.
  - `test_require_level_enforcement`: Verified `AuthLevelError` raised on unauthorized operations.
  - `test_verify_order_ownership`: Verified `OwnershipError` raised on cross-customer access.
  - `test_eligibility_within_30_days`: PASS (10-day old order eligible for ₹1,499).
  - `test_eligibility_expired_window`: PASS (35-day old order rejected with exact policy explanation).
  - `test_eligibility_digital_goods_rejected`: PASS (Store Policy 6.0 non-refundable digital items enforced).
  - `test_eligibility_already_refunded_rejected`: PASS (Double-refund attempts blocked).
  - `test_eligibility_undelivered_order_rejected`: PASS (Orders in `Processing` cannot be refunded).
  - `test_evaluate_refund_state_under_limit`: PASS (₹1,499 <= ₹2,000 -> `RefundState.PROCESSED`).
  - `test_evaluate_refund_state_over_limit`: PASS (₹4,500 > ₹2,000 -> `RefundState.PENDING_APPROVAL`).
  - `test_idempotency_key_consistency`: PASS (Deterministic SHA-256 keys generated).

### Git Version Control
- **Action:** Staged and committed core domain models, ports, and tests.
- **Commit:** `feat(core): implement domain models, abstract ports, and deterministic policy engine`

---

## [Task-02] - MockShop Adapters (Catalog, Orders, Refunds)
**Timestamp:** 2026-11-02 16:38:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Build concrete, decoupled in-memory implementations of `CatalogPort`, `OrderPort`, and `RefundPort` to allow rapid, zero-dependency, local testing of the complete store lifecycle.
- Seed the system with realistic data explicitly designed to validate critical edge cases:
  - Look-alike product pairs (*Pulse Buds 141* vs *Pulse Buds 131*) to test disambiguation.
  - Diverse orders: eligible for refund (`ORD-1029`), shipped/in-transit (`ORD-1030`), auto-refund under ₹2,000 (`ORD-5501`), over-limit requiring approval (`ORD-8812`), digital non-refundable goods (`ORD-7721`), and cross-customer security boundaries (`ORD-9999`).
  - Idempotency tracking and Support Desk staff decision workflow.

### Architectural Boundaries & Modularity
- `adapters/mockshop/catalog_adapter.py`: Implements `CatalogPort`. Resolves names and aliases via hybrid scoring, provides live pricing/discounts, and isolates document chunks strictly per `product_id`.
- `adapters/mockshop/order_adapter.py`: Implements `OrderPort`. Enforces ownership verification (returning `None` for unowned orders), delivers chronological shipping tracking timelines.
- `adapters/mockshop/refund_adapter.py`: Implements `RefundPort`. Integrates with `policy_engine` for eligibility, evaluates ₹2,000 auto-limit vs supervisor approval, caches idempotency keys, and supports Support Desk staff approve/reject transitions.
- `adapters/mockshop/__init__.py`: Clean module exports for the mockshop package.
- Zero socket dependencies: Uses synchronous driving in unit tests to ensure deterministic execution in sandboxed environments.

### Files Touched
- `support-assistant/adapters/mockshop/catalog_adapter.py` (Created - CatalogPort adapter with seed products and look-alikes)
- `support-assistant/adapters/mockshop/order_adapter.py` (Created - OrderPort adapter with ownership checks and tracking)
- `support-assistant/adapters/mockshop/refund_adapter.py` (Created - RefundPort adapter with idempotency and staff decision recording)
- `support-assistant/adapters/mockshop/__init__.py` (Created - Package exports)
- `support-assistant/adapters/__init__.py` (Created - Top-level adapters package)
- `support-assistant/tests/test_mockshop_adapters.py` (Created - 10 comprehensive integration tests for adapters)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_mockshop_adapters.py`
- **Result:** **10/10 Integration Tests Passed (100.0% in 0.001s)**
  - `test_catalog_exact_and_lookalike_search`: PASS (Identified P1041 exact score >=0.90, captured both 141 and 131 on broad query).
  - `test_catalog_get_details_and_live_price`: PASS (Exact specs and live discount prices retrieved).
  - `test_catalog_search_product_docs_confined`: PASS (Zero document leaks across product IDs).
  - `test_order_lookup_with_ownership_enforcement`: PASS (Unowned ORD-9999 returns None).
  - `test_order_tracking_events`: PASS (Chronological shipment events returned).
  - `test_refund_under_2000_processed`: PASS (₹1,499 approved automatically).
  - `test_refund_over_2000_pending_approval`: PASS (₹4,500 held for supervisor review).
  - `test_refund_idempotency_replay`: PASS (Repeated request with same key returns identical result).
  - `test_refund_digital_goods_rejection`: PASS (Store Policy 6.0 digital item rejected).
  - `test_staff_decision_recording`: PASS (Pending refund approved with staff identity and timestamp).
- **Regression Command:** `python support-assistant/tests/test_core_policy.py` -> **11/11 tests passed**.

### Git Version Control
- **Action:** Staged and committed mockshop adapters and test suite.
- **Commit:** `feat(adapters): implement mockshop catalog, order, and refund adapters with test suite`

---

## [Task-03] - PostgreSQL + pgvector Setup, Schema DDL & Ingestion Pipeline
**Timestamp:** 2026-11-02 17:19:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Establish unified database infrastructure for relational data, dense vector search (`pgvector`), and trigram fuzzy matching (`pg_trgm`) per Specification Sections 4, 5, and 8.
- Implement production-grade knowledge ingestion pipeline conforming to Section 5.3:
  - Prefix every chunk with product name (e.g. `Pulse Buds 141 - Battery life: ...`) to eliminate cross-product ambiguity.
  - Chunk returns and refund policy documents strictly by clause (`Policy Clause X.X`).
  - Strip navigation and live pricing boilerplate from vector storage.
  - Provide multi-backend embedding adapters (zero-dependency `DeterministicLocalEmbedder` for offline testing, plus `NIMEmbedder` for NVIDIA NIM microservices).
- Provide `docker-compose.yml` for unified `pgvector/pgvector:pg16` and `redis:7-alpine` deployment.

### Architectural Boundaries & Modularity
- `support-assistant/db/init.sql`: Production DDL defining `products`, `product_specs`, `product_prices`, `knowledge_chunks` (with 1024-dim vector column & HNSW index), `orders`, `order_items`, `refund_requests`, and `traces`.
- `docker-compose.yml`: Multi-container configuration with health checks, environment parameters, and volume persistence.
- `support-assistant/ingestion/chunker.py`: `KnowledgeChunker` enforcing Section 5.3 rules.
- `support-assistant/ingestion/embedder.py`: `BaseEmbedder` protocol, `DeterministicLocalEmbedder` (1024-dim CPU-based normalized vectors), and `NIMEmbedder` (NVIDIA NIM integration).
- `support-assistant/ingestion/pipeline.py`: Ingestion pipeline loading product and policy documents, computing embeddings, and executing filtered RAG vector retrieval (`WHERE product_id = :p_id`).
- `support-assistant/data/`: Canonical datasets (`returns_policy.txt` and `sample_products.json`).

### Files Touched
- `support-assistant/db/init.sql` (Created - PostgreSQL schema DDL with pgvector & pg_trgm)
- `docker-compose.yml` (Created - Docker Compose configuration for PostgreSQL and Redis)
- `support-assistant/ingestion/chunker.py` (Created - Knowledge chunker enforcing Section 5.3 rules)
- `support-assistant/ingestion/embedder.py` (Created - Embedder adapters for local CPU and NVIDIA NIM)
- `support-assistant/ingestion/pipeline.py` (Created - End-to-end ingestion and vector search runner)
- `support-assistant/ingestion/__init__.py` (Created - Ingestion package exports)
- `support-assistant/data/returns_policy.txt` (Created - Store policy clauses)
- `support-assistant/data/sample_products.json` (Created - Structured product documentation)
- `support-assistant/tests/test_ingestion_and_db.py` (Created - 6 unit and integration tests)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_ingestion_and_db.py`
- **Result:** **6/6 Tests Passed (100.0% in 0.004s)**
  - `test_init_sql_schema_definitions`: PASS (Verified vector extension, HNSW index, and all 12 tables).
  - `test_docker_compose_config`: PASS (Verified pgvector:pg16 and redis:7-alpine).
  - `test_chunk_product_doc_prefixing_rule`: PASS (Product name prefixing confirmed; boilerplate stripped).
  - `test_chunk_policy_doc_by_clause`: PASS (Clauses 1.0, 2.0, 3.0, 6.0, 7.0 cleanly separated into chunks).
  - `test_deterministic_local_embedder`: PASS (1024-dim vectors L2 normalized to 1.0; semantic similarity holds).
  - `test_ingestion_pipeline_end_to_end_and_filtered_rag`: PASS (Zero leakage across look-alike products).
- **Full Suite Regression:** 27/27 tests passed across all 3 test suites (`test_core_policy`, `test_mockshop_adapters`, `test_ingestion_and_db`).

### Git Version Control
- **Action:** Staged and committed PostgreSQL schema, docker-compose, and ingestion pipeline.
- **Commit:** `feat(db): add postgres pgvector schema, docker-compose, and ingestion pipeline`

---

## [Task-04] - FastMCP Tool Servers & Dispatcher with Transport-Level Auth
**Timestamp:** 2026-11-02 17:27:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Build modular MCP tool servers (`catalog-server`, `order-server`, `refund-server`, and `handoff-server`) adhering to the principle of least privilege.
- Solve the MCP identity problem specified in Section 7.6 & 15.1: The model must **never** supply `customer_id` or authorization credentials. Identity is passed via transport headers as a short-lived internal signed token (`Authorization: Bearer <token>`).
- Enforce that the refund server requires step-up OTP verification (`AuthLevel.VERIFIED`), preventing unauthorized financial refunds.
- Record execution traces for all tool calls including latencies and authorization levels for R5 Explainability.

### Architectural Boundaries & Modularity
- `services/mcp_servers/auth.py`: Token minting and decoding (`mint_internal_token` & `ctx_from_token`) using HS256 JWTs with 5-minute lifetimes.
- `services/mcp_servers/catalog_server.py`: Wraps `CatalogPort` for `find_product`, `get_product_price`, `get_product_details`, `search_product_docs`, and `search_policy`.
- `services/mcp_servers/order_server.py`: Wraps `OrderPort` for `get_order_status`, `list_recent_orders`, and `get_tracking`. Enforces `IDENTIFIED` auth level and customer ownership.
- `services/mcp_servers/refund_server.py`: Wraps `RefundPort` for `check_refund_eligibility`, `create_refund_request`, and `get_refund_status`. Enforces `VERIFIED` step-up OTP and ₹2,000 auto-limit boundaries.
- `services/mcp_servers/handoff_server.py`: Handles human escalations and ticket assignment.
- `services/mcp_servers/dispatcher.py`: Acts as the unified MCP Client / Router for the worker orchestrator. Injects transport tokens, dispatches tool execution, and appends execution traces.

### Files Touched
- `support-assistant/services/mcp_servers/auth.py` (Created - Transport auth token minting and decoding)
- `support-assistant/services/mcp_servers/catalog_server.py` (Created - MCP Catalog Server)
- `support-assistant/services/mcp_servers/order_server.py` (Created - MCP Order Server)
- `support-assistant/services/mcp_servers/refund_server.py` (Created - MCP Refund Server)
- `support-assistant/services/mcp_servers/handoff_server.py` (Created - MCP Handoff Server)
- `support-assistant/services/mcp_servers/dispatcher.py` (Created - Unified MCP Tool Dispatcher)
- `support-assistant/services/mcp_servers/__init__.py` (Created - Package exports)
- `support-assistant/tests/test_mcp_servers.py` (Created - 9 unit and integration tests)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_mcp_servers.py`
- **Result:** **9/9 Tests Passed (100.0% in 0.005s)**
  - `test_mcp_tool_schemas_hide_identity`: PASS (Verified that `customer_id`, `auth_token`, `level`, and `tenant_id` are completely hidden from model schemas).
  - `test_internal_token_mint_and_decode`: PASS (Verified short-lived token correctly reconstructs `SessionContext`).
  - `test_order_server_requires_identified_level`: PASS (Anonymous requests return `needs_auth: login_required`).
  - `test_order_server_enforces_ownership`: PASS (Cross-account access blocked).
  - `test_refund_server_requires_verified_otp_level`: PASS (Identified requests return `needs_auth: otp_required`).
  - `test_refund_auto_limit_under_2000_vs_over_2000`: PASS (₹1,499 auto-processed; ₹4,500 held for supervisor review).
  - `test_catalog_server_find_product_and_price`: PASS (Resolved product specs and live prices).
  - `test_handoff_server_creates_ticket`: PASS (Ticket generated with `ESC-` prefix).
  - `test_dispatcher_records_explainability_traces`: PASS (Traces recorded with latencies and auth levels).
- **Full Project Regression:** **36/36 tests passed** across all 4 test suites (`test_core_policy`, `test_mockshop_adapters`, `test_ingestion_and_db`, `test_mcp_servers`).

### Git Version Control
- **Action:** Staged and committed MCP tool servers and dispatcher.
- **Commit:** `feat(mcp): implement modular fastmcp tool servers with transport auth and trace dispatcher`

---

## [Task-05] - Router, Language Normalizer & Redis Cache Layer
**Timestamp:** 2026-11-02 17:31:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement intelligent query routing and cost control mechanisms per Specification Sections 3.3, 9.1, 11, and 12.
- Eliminate LLM API costs for high-frequency queries using zero-cost templates for greetings and verified order tracking.
- Implement cache-aside with fine-grained TTLs (45s for price, 10s for orders, never cache refunds).
- Normalizer supports English, Tamil, and Tanglish without translating IDs, model numbers, or currency amounts.
- Automatically route simple requests to the small model tier (Groq 8B) and complex disputes/comparisons to the large model tier (Groq 70B).

### Architectural Boundaries & Modularity
- `core/router/normalizer.py`: Language detection, entity extraction, dispute and comparison flagging.
- `core/router/cache.py`: Cache-aside service enforcing TTL policies and product cache invalidation.
- `core/router/templates.py`: Deterministic template renderer across English, Tamil, and Tanglish.
- `core/router/router.py`: Multi-tier router deciding between cache, template, small model, large model, and handoff.

### Files Touched
- `support-assistant/core/router/normalizer.py` (Created - Language detection and entity extraction)
- `support-assistant/core/router/cache.py` (Created - Fine-grained TTL cache-aside service)
- `support-assistant/core/router/templates.py` (Created - Multilingual zero-cost template responder)
- `support-assistant/core/router/router.py` (Created - AI multi-tier request router)
- `support-assistant/core/router/__init__.py` (Created - Router package exports)
- `support-assistant/tests/test_router_and_cache.py` (Created - 9 unit and integration tests)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_router_and_cache.py`
- **Result:** **9/9 Tests Passed (100.0% in 0.002s)**
  - `test_language_detection`: PASS (English, Tamil script, and Tanglish detected accurately).
  - `test_entity_extraction`: PASS (Extracted `ORD-5501` and `₹1,499`).
  - `test_cache_ttl_and_invalidation`: PASS (Key invalidation on re-ingest verified).
  - `test_greeting_template_route`: PASS (Matched zero-cost greeting template).
  - `test_order_status_template_route`: PASS (Rendered verified order status template).
  - `test_comparison_routes_to_large_model`: PASS (Pulse Buds 141 vs 131 routed to large model).
  - `test_customer_dispute_routes_to_large_model`: PASS (Agitated dispute routed to large model).
  - `test_human_handoff_route`: PASS (Human request routed to handoff queue).
  - `test_standard_faq_routes_to_small_model`: PASS (Standard FAQ routed to fast small model).
- **Full Project Regression:** **45/45 tests passed** across all 5 test suites.

### Git Version Control
- **Action:** Staged and committed router, normalizer, and cache-aside service.
- **Commit:** `feat(router): implement multilingual normalizer, cache-aside, and multi-tier router`

---

## [Task-06] - Worker Orchestrator & LLM Integration (Groq & NIM)
**Timestamp:** 2026-11-02 17:34:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement the end-to-end conversational agent orchestrator coordinating routing, look-alike product disambiguation, tool execution via MCP dispatcher, and grounded synthesis per Specification Section 3.2, 7, 8, 9, and 13.
- Implement tiered Groq API integration (`llama-3.1-8b-instant` for small tier, `llama-3.3-70b-versatile` for large tier) with a zero-cost deterministic mock engine for offline test execution.
- Implement Section 8 Look-Alike Disambiguation Gate: when a customer mentions ambiguous models (e.g. "Pulse Buds" without 141 or 131), detects multiple candidate matches and asks a clarifying choice question rather than guessing.
- Enforce Step-up OTP requirements: flags `requires_action='needs_otp'` when an identified session requests a refund without OTP verification.

### Architectural Boundaries & Modularity
- `services/worker/llm_client.py`: `LLMClient` protocol, `GroqLLMClient` (OpenAI-compatible), and `MockLLMClient` (deterministic offline engine).
- `services/worker/orchestrator.py`: `WorkerOrchestrator` handling the 6-stage lifecycle (route check -> cache fast path -> template fast path -> handoff fast path -> look-alike gate -> LLM tool loop).

### Files Touched
- `support-assistant/services/worker/llm_client.py` (Created - Groq API & Mock LLM client adapters)
- `support-assistant/services/worker/orchestrator.py` (Created - Worker Orchestrator and look-alike disambiguation gate)
- `support-assistant/services/worker/__init__.py` (Created - Worker package exports)
- `support-assistant/tests/test_worker_orchestrator.py` (Created - 10 unit and integration tests)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_worker_orchestrator.py`
- **Result:** **10/10 Tests Passed (100.0% in 0.007s)**
  - `test_greeting_fast_path`: PASS (Template route bypassed LLM).
  - `test_verified_order_status_template_fast_path`: PASS (Rendered verified tracking).
  - `test_lookalike_disambiguation_pulse_buds`: PASS (Ambiguity gate generated clarifying choice prompt).
  - `test_single_product_inquiry_with_specs_and_price`: PASS (Called price and docs tools; synthesized exact specs).
  - `test_auto_refund_under_2000`: PASS (₹1,499 auto-approved; 3-5 days timeline).
  - `test_supervisor_approval_refund_over_2000`: PASS (₹4,500 held for supervisor review; 24-48h turnaround).
  - `test_refund_without_otp_requires_stepup`: PASS (Action flagged `needs_otp`).
  - `test_digital_goods_refund_rejection`: PASS (Store Policy 6.0 refusal enforced).
  - `test_human_handoff_fast_path`: PASS (Escalation ticket generated).
  - `test_prompt_injection_refusal`: PASS (Override attempt neutralized).
- **Full Project Regression:** **55/55 unit tests passed** across all 6 test suites.

### Git Version Control
- **Action:** Staged and committed worker orchestrator, look-alike gate, and LLM client adapters.
- **Commit:** `feat(worker): implement conversational worker orchestrator, look-alike gate, and groq llm integration`

---

## [Task-07] - Grounding Verification & Explainability Tracing (R5)
**Timestamp:** 2026-11-02 17:43:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement pre-transmission anti-hallucination verification gate (Section 9.2, 9.3) ensuring all price quotes, stock counts, delivery dates, and refund state claims are strictly backed by tool execution results.
- Implement DPDP Act compliant PII masking (`PIIMasker`) sanitizing phone numbers, emails, credit cards, and OTP codes before logging.
- Implement `TraceCollector` recording per-turn factual evidence per Section 14.1 and powering the Support Desk "Why This Answer" view (Section 14.2 & R5 Explainability).

### Architectural Boundaries & Modularity
- `core/tracing/pii_masker.py`: Reusable regex-based privacy scrubber for customer phone numbers, emails, credit cards, and OTP codes.
- `core/tracing/grounding_verifier.py`: Automated pre-transmission verification gate evaluating claims against tool output corpus.
- `core/tracing/trace_collector.py`: Per-turn trace recorder and "Why This Answer" view builder.

### Files Touched
- `support-assistant/core/tracing/pii_masker.py` (Created - PII masking utility)
- `support-assistant/core/tracing/grounding_verifier.py` (Created - Grounding verification and anti-hallucination gate)
- `support-assistant/core/tracing/trace_collector.py` (Created - Trace collector & 'Why This Answer' inspector)
- `support-assistant/core/tracing/__init__.py` (Created - Tracing package exports)
- `support-assistant/tests/test_tracing_and_grounding.py` (Created - 7 unit and integration tests)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_tracing_and_grounding.py`
- **Result:** **7/7 Tests Passed (100.0% in 0.001s)**
  - `test_pii_masking_emails_phones_cards`: PASS (Customer emails, phones, and credit card numbers masked).
  - `test_grounding_verifier_valid_facts_pass`: PASS (Factual tool-grounded claims approved).
  - `test_grounding_verifier_hallucinated_price_fails`: PASS (Ungrounded price claims blocked).
  - `test_grounding_verifier_unbacked_refund_claim_fails`: PASS (Unverified refund approval claims blocked).
  - `test_grounding_verifier_pii_leak_rejected`: PASS (Raw card number echoes blocked).
  - `test_trace_collector_records_turn_conforming_to_spec`: PASS (All Section 14.1 trace fields recorded).
  - `test_why_this_answer_view_structure`: PASS (Support Desk 'Why This Answer' view generated).
- **Full Project Regression:** **62/62 unit tests passed** across all 7 test suites.

### Git Version Control
- **Action:** Staged and committed PII masker, grounding verifier, and trace collector.
- **Commit:** `feat(tracing): implement pii masking, pre-transmission grounding verifier, and trace collector`

---

## [Task-08] - Channel Gateway & Assistant API Service (ASGI / FastAPI & WhatsApp)
**Timestamp:** 2026-11-02 17:55:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Build the Channel Gateway and Assistant API service connecting frontend channels (Website chat widget and Meta WhatsApp Cloud API) to the internal core orchestrator per Specification Section 15.1 and 15.2.
- Implement Section 15.1 Auth Hierarchy:
  - Anonymous sessions for unregistered visitors with basic FAQ capabilities.
  - Identified customer sessions via customer JWT Bearer token verification (`POST /chat/messages` with `Authorization: Bearer <token>`).
  - Verified customer sessions via secure OTP step-up challenge (`POST /auth/otp/send` and `POST /auth/otp/verify`).
- Implement WhatsApp Cloud API security per Section 15.1.1:
  - Meta Webhook Subscription Verification handshake (`GET /webhooks/whatsapp` with `hub.mode`, `hub.challenge`, and `hub.verify_token`).
  - Cryptographic payload integrity verification using Meta's `X-Hub-Signature-256` header (HMAC-SHA256 with `app_secret` via `hmac.compare_digest`).
  - WhatsApp message deduplication cache using `wamid` message IDs to prevent duplicate processing on network retries.
  - WhatsApp Fast ACK response (immediate 200 OK delivery acknowledgment).
- Implement standard ASGI 3.0 interface for zero-dependency execution with `uvicorn` or any ASGI server in production, accompanied by typed Pydantic request/response schemas.

### Architectural Boundaries & Modularity
- `services/assistant_api/jwt_auth.py`: Storefront customer JWT verifier and minting helper. Parses customer identity (`sub`), validates tenant isolation, and automatically downgrades invalid or expired tokens to `ANONYMOUS` without throwing unhandled exceptions.
- `services/assistant_api/otp_service.py`: Step-up OTP engine. Generates 6-digit numeric codes with `secrets`, stores salted SHA-256 digests, enforces 5-minute TTL, locks out after 3 failed attempts, and promotes sessions to `AuthLevel.VERIFIED` with a 15-minute validity window.
- `services/assistant_api/whatsapp_security.py`: Meta webhook validation and message deduplication cache with sliding expiration window.
- `services/assistant_api/gateway_app.py`: Production Channel Gateway implementing standard ASGI 3.0 and REST endpoints (`/chat/messages`, `/webhooks/whatsapp`, `/auth/otp/send`, `/auth/otp/verify`, `/health`).
- `services/assistant_api/__init__.py`: Clean module exports.
- `tests/test_assistant_api.py`: 10 unit and integration tests covering JWT verification, OTP lifecycle, WhatsApp HMAC, deduplication, and ASGI endpoints without OS socket dependencies.

### Files Touched
- `support-assistant/services/assistant_api/jwt_auth.py` (Created - Customer JWT minting and verification)
- `support-assistant/services/assistant_api/otp_service.py` (Created - Step-up OTP challenge service with constant-time verification)
- `support-assistant/services/assistant_api/whatsapp_security.py` (Created - Meta webhook HMAC verification and message deduplicator)
- `support-assistant/services/assistant_api/gateway_app.py` (Created - Channel Gateway & Assistant API ASGI Application)
- `support-assistant/services/assistant_api/__init__.py` (Created - Gateway package exports)
- `support-assistant/tests/test_assistant_api.py` (Created - 10 unit and integration tests)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_assistant_api.py`
- **Result:** **10/10 Tests Passed (100.0% in 0.005s)**
  - `test_customer_jwt_mint_and_verify`: PASS (Valid Bearer token resolved to `IDENTIFIED` level).
  - `test_customer_jwt_tenant_mismatch_downgrades`: PASS (Cross-tenant token safely downgraded to `ANONYMOUS`).
  - `test_customer_jwt_invalid_or_missing_header`: PASS (Missing/tampered token defaults to `ANONYMOUS`).
  - `test_otp_challenge_and_verification`: PASS (Salted SHA-256 OTP verified; session upgraded to `VERIFIED`).
  - `test_otp_lockout_after_three_attempts`: PASS (Challenge invalidated after 3 failed attempts).
  - `test_whatsapp_webhook_handshake`: PASS (Meta GET handshake verified; invalid tokens return 403).
  - `test_whatsapp_signature_verification_and_deduplication`: PASS (HMAC-SHA256 verified; duplicate `wamid` acknowledged without re-execution).
  - `test_gateway_chat_anonymous_to_identified`: PASS (Full chat route with auth escalation verified).
  - `test_gateway_otp_step_up_flow`: PASS (End-to-end send -> verify -> verified chat flow confirmed).
  - `test_gateway_health`: PASS (`GET /health` returns 200 OK and active session count).
- **Full Project Unit Regression:** **72/72 tests passed** across all 8 test suites.
- **Evaluation Benchmark Regression:** **10/10 scenarios passed (100.0%)** via `run_evals.py`.
- **Total Combined Tests:** **82/82 tests passing (100%)**.

### Git Version Control
- **Action:** Staged and committed Channel Gateway, WhatsApp security, OTP service, and test suite.
- **Commit:** `feat(gateway): implement fastapi chat api, whatsapp webhook, and otp challenge service`

---

## [Task-09] - Comprehensive Pytest, Adversarial Red-Team & Policy Verification Suite
**Timestamp:** 2026-11-02 18:07:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Conduct end-to-end security red-teaming, adversarial evaluation, and deterministic policy boundary testing per Specification Sections 1.2 (R1-R5), 6, 7.6, 8, 9, 10, 11, 12, 14, and 15.
- Validate that the core architectural principle: *"The LLM understands and phrases. Code decides and acts."* holds under active adversarial attempts.
- Verify that financial operations (refunds > ₹2,000, 30-day physical return window, non-refundable digital goods, OTP step-up verification) cannot be circumvented via prompt injections, authority claims, developer mode overrides, or multilingual phrasing.
- Verify horizontal multi-tenant isolation and IDOR protection: customers cannot snoop or refund other customers' orders.
- Verify R4 budget protection: festival spike (10× traffic) resilience where greetings and verified order tracking consume 0 LLM tokens.
- Verify DPDP PII scrubbing and Section 14.1 / R5 Explainability audit trace generation.

### Architectural Boundaries & Modularity
- `support-assistant/tests/test_adversarial_and_evals.py`: Modular test harness spanning 5 test suites:
  1. `TestAdversarialSecurityAndRedTeaming`: Direct jailbreaks, management override claims, indirect injections in order tracking notes, Tanglish injection attempts, and SQLi / XSS fuzzing inputs.
  2. `TestHorizontalPrivilegeEscalation`: Cross-account order inspection denial, cross-account refund denial, and verification that model tool schemas expose zero auth or identity parameters.
  3. `TestDeterministicPolicyBoundaries`: Exact ₹2,000 auto-refund threshold boundary (₹2,000 auto vs ₹2,001 supervisor review), 30 vs 31-day return window, undelivered order refund block, and idempotency key replay consistency.
  4. `TestFestivalSpikeAndCostControl`: Zero-cost template routes for greetings across English, Tamil, and Tanglish; zero-cost order tracking for verified sessions; cache hit validation within 45s TTL.
  5. `TestExplainabilityAndPIIScrubbing`: DPDP PII masking for phone numbers, emails, credit cards, and OTPs; anti-hallucination pre-transmission grounding verifier; Section 14.1 trace generation and Support Desk "Why This Answer" view.
- Zero socket dependencies: All tests driven in-memory via synchronous coroutine stepping.

### Files Touched
- `support-assistant/tests/test_adversarial_and_evals.py` (Created - 18 comprehensive adversarial and policy verification tests)
- `support-assistant/core/router/normalizer.py` (Modified - Added 'vanakkam' to Tanglish markers for greeting language detection)
- `support-assistant/core/router/router.py` (Modified - Added Tamil script 'வணக்கம்' to greeting template triggers)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_adversarial_and_evals.py`
- **Result:** **18/18 Tests Passed (100.0% in 0.005s)**
  - `test_direct_prompt_injection_jailbreak_refusal`: PASS (Override attempt blocked; no refund executed).
  - `test_policy_override_injection_refusal`: PASS (Management override claims rejected; Policy 6.0 enforced).
  - `test_indirect_prompt_injection_in_data_payload`: PASS (Injection inside tracking query neutralized; 0 secret leaks).
  - `test_multilingual_injection_in_tanglish`: PASS (Tanglish injection blocked; step-up OTP enforced).
  - `test_sqli_and_xss_fuzzing_resilience`: PASS (SQLi, path traversal, null bytes normalized safely without crash).
  - `test_customer_cannot_view_another_customers_order`: PASS (Cross-customer order masked as not found).
  - `test_customer_cannot_refund_another_customers_order`: PASS (Cross-customer refund rejected).
  - `test_identity_injected_via_tool_arguments_is_ignored`: PASS (All 6 tool schemas validated zero customer_id/token leakage).
  - `test_exact_2000_inr_auto_refund_boundary`: PASS (₹2,000 processed; ₹2,001 pending approval).
  - `test_return_window_boundary_day_30_vs_day_31`: PASS (Day 30 eligible; Day 31 strictly rejected).
  - `test_undelivered_order_cannot_be_refunded`: PASS (In-transit order rejected).
  - `test_idempotency_replay_returns_identical_transaction`: PASS (Replay returns identical transaction without side-effects).
  - `test_festival_greeting_burst_zero_llm_cost`: PASS (Zero-token template response across en, ta, tanglish).
  - `test_festival_order_tracking_burst_zero_llm_cost`: PASS (Zero-token template tracking for verified customers).
  - `test_price_cache_hit_prevents_repeat_computation`: PASS (Cache hit within 45s TTL confirmed).
  - `test_dpdp_pii_masking_comprehensive`: PASS (Phones, emails, cards, and OTPs scrubbed).
  - `test_grounding_verifier_catches_unbacked_refund_claims`: PASS (Ungrounded refund claims blocked).
  - `test_complete_r5_audit_trace_generation`: PASS (Section 14.1 trace and 'Why This Answer' view generated).
- **Full Project Unit Regression:** **90/90 tests passed across all 9 test suites (in 0.024s)**.
- **Evaluation Benchmark Regression:** **10/10 scenarios passed (100.0%)** via `run_evals.py`.
- **Total Combined Tests:** **100 / 100 tests passing (100.0%)**.

### Git Version Control
- **Action:** Staged and committed adversarial test suite, router improvements, and test logs.
- **Commit:** `feat(evals): add comprehensive adversarial test suite, red-team fuzzing, and policy verification`

---

## [Task-10] - Support Desk Staff Backend, Frontend UIs & Production Packaging
**Timestamp:** 2026-11-02 18:16:00 IST  
**Status:** COMPLETED & VERIFIED (FINAL MILESTONE)

### Objective & Rationale ("Why")
- Build the final operational capabilities specified in Section 10.3 (Support Desk Staff approval for refunds > ₹2,000) and Section 14.2 (Supervisor "Why This Answer" audit trace viewer).
- Provide production-grade, interactive frontends:
  - **Customer Web Chat Widget (`static/widget/index.html`):** Clean, responsive customer interface supporting English, Tamil, and Tanglish, quick action prompt chips, real-time OTP challenge modal for step-up verification, and live REST integration.
  - **Support Desk Supervisor Console (`static/desk/index.html`):** Executive dashboard displaying pending refund approval requests (> ₹2,000 threshold), one-click approve/reject actions with mandatory audit notes, and interactive modal inspecting per-turn factual grounding traces and DPDP-scrubbed evidence.
- Finalize production containerization with `support-assistant/Dockerfile`, `requirements.txt`, and enhanced `docker-compose.yml` linking all services (`assistant-api`, `postgres` with `pgvector`, and `redis`).

### Architectural Boundaries & Modularity
- `services/support_desk/app.py`: `SupportDeskService` managing pending refund queues, staff approval/rejection decision recording with timestamps and notes, explainability trace retrieval, and operational metrics calculation.
- `services/assistant_api/gateway_app.py`: ASGI gateway serving static frontend assets (`/widget` and `/desk`) alongside REST endpoints (`/desk/refunds/pending`, `/desk/refunds/{id}/approve`, `/desk/refunds/{id}/reject`, `/desk/traces/{id}`, `/desk/stats`).
- `static/widget/index.html`: Standalone single-page customer chat widget with NovaRetail branding, real-time OTP step-up modal, and live REST communication.
- `static/desk/index.html`: Standalone supervisor console with live metrics cards, pending refund table, approval modal, and "Why This Answer" JSON inspector.
- `tests/test_support_desk.py`: 6 unit and integration tests validating pending queues, staff approval/rejection workflows, trace inspections, and static UI delivery.
- `Dockerfile` & `docker-compose.yml`: Multi-container production packaging with healthchecks and environment configuration.

### Files Touched
- `support-assistant/services/support_desk/app.py` (Created - Support Desk backend service)
- `support-assistant/services/support_desk/__init__.py` (Created - Package exports)
- `support-assistant/static/widget/index.html` (Created - Customer Web Chat Widget)
- `support-assistant/static/desk/index.html` (Created - Support Desk Supervisor Console)
- `support-assistant/services/assistant_api/gateway_app.py` (Modified - Added support desk and static UI routing)
- `support-assistant/tests/test_support_desk.py` (Created - 6 unit and integration tests)
- `support-assistant/requirements.txt` (Created - Production Python dependencies)
- `support-assistant/Dockerfile` (Created - Production container definition)
- `docker-compose.yml` (Modified - Added assistant-api service)

### Verification & Quality Assurance
- **Command Executed:** `python support-assistant/tests/test_support_desk.py`
- **Result:** **6/6 Tests Passed (100.0% in 0.003s)**
  - `test_get_pending_refunds_filters_by_threshold`: PASS (Only refunds > ₹2,000 held for supervisor review).
  - `test_supervisor_approve_refund`: PASS (Approved by staff with audit notes; queue cleared).
  - `test_supervisor_reject_refund_requires_mandatory_notes`: PASS (Mandatory audit note enforced on rejection).
  - `test_why_this_answer_trace_inspection`: PASS (Section 14.2 explainability trace and DPDP masking confirmed).
  - `test_support_desk_api_endpoints_via_gateway`: PASS (All `/desk/*` REST endpoints verified via ASGI).
  - `test_static_ui_widget_and_desk_delivery`: PASS (`/widget` and `/desk` HTML delivery verified).
- **Full Project Unit Regression:** **96/96 tests passed across all 10 test suites (in 0.027s)**.
- **Evaluation Benchmark Regression:** **10/10 scenarios passed (100.0%)** via `run_evals.py`.
- **Total Combined Tests:** **106 / 106 Tests Passing (100.0%)**.

### Git Version Control
- **Action:** Staged and committed Support Desk service, customer chat widget, supervisor console, and production packaging.
- **Commit:** `feat(desk): implement support desk supervisor dashboard, customer web widget, and production packaging`

---

## Project Completion Progress: 100.0% (11 / 11 Milestones Completed)

### All Specification Milestones Fully Implemented & Verified:
1. `[Task-00]` Foundation, Skills, & Evaluation Baseline (100%)
2. `[Task-01]` Core Domain Models, Abstract Ports & Deterministic Policy Engine (100%)
3. `[Task-02]` MockShop Adapters & Seed Look-Alikes (100%)
4. `[Task-03]` PostgreSQL + pgvector Schema DDL & Chunking Pipeline (100%)
5. `[Task-04]` FastMCP Tool Servers with Identity Protection (100%)
6. `[Task-05]` Router, Multilingual Normalizer & Cache-Aside Layer (100%)
7. `[Task-06]` Worker Orchestrator & Groq/NIM LLM Integration (100%)
8. `[Task-07]` Grounding Verification & Explainability Tracing (100%)
9. `[Task-08]` Gateway & WhatsApp Channel Webhooks (100%)
10. `[Task-09]` Comprehensive Pytest & Adversarial Red-Team Suite (100%)
11. `[Task-10]` Support Desk Supervisor Dashboard, Customer Web Widget & Production Packaging (100%)


---

## [Task-11] - Full-Stack eCommerce Platform (100 Products, Next.js, React, SQLite REST API)
**Timestamp:** 2026-11-02 18:47:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Build a complete, functional e-commerce website with 100 products across 8 realistic departments using Next.js, React, and SQLite in a dedicated `ecommerce-app/` folder.
- Incorporate comprehensive features derived from modern 2026 e-commerce benchmarks (predictive live search, faceted multi-attribute filtering, high-converting PDP galleries, urgent stock badges, reviews engine, slide-over cart drawer, promo code discounts, streamlined multi-step checkout, atomic inventory decrements, and real-time order tracking).
- Enforce strict separation between frontend and backend directories (`ecommerce-app/frontend/` and `ecommerce-app/backend/`).

### Architectural Boundaries & Modularity
- **Backend Directory (`ecommerce-app/backend/`)**:
  - `src/db/database.js`: Zero-dependency native SQLite database via Node's `node:sqlite` (`DatabaseSync`), enforcing ACID transactions and indexed lookups.
  - `src/db/seed.js`: Deterministic seeder populating 100 products, 8 categories, customer reviews, and promotional discount codes.
  - `src/server.js`: Clean REST API exposing endpoints for product search/facets, single product details with reviews, category counts, promo validation, atomic order creation with inventory decrement, review submissions, and order tracking.
- **Frontend Directory (`ecommerce-app/frontend/`)**:
  - Next.js 14 App Router with React 18, Tailwind CSS, and Lucide React.
  - `context/CartContext.js` & `context/WishlistContext.js`: LocalStorage-persisted application states.
  - Reusable presentation components: `Navbar`, `Footer`, `ProductCard`, `CartDrawer`, `FilterSidebar`, and `Toast`.
  - Routes: `/` (catalog & facets), `/product/[id]` (PDP), `/cart` (full cart), `/checkout` (checkout), `/order-confirmation/[id]` (receipt & tracking), `/wishlist` (saved items), and `/orders` (order lookup).
- **Launcher Scripts**: `start.bat` and `start.ps1` for one-click startup of both services.

### Files Touched
- `ecommerce-app/backend/package.json` (Created - Backend metadata and scripts)
- `ecommerce-app/backend/src/db/database.js` (Created - SQLite schema & connection)
- `ecommerce-app/backend/src/db/seed.js` (Created - 100 products, categories, coupons, and reviews seeder)
- `ecommerce-app/backend/src/server.js` (Created - REST API server with CORS and error handling)
- `ecommerce-app/frontend/package.json` (Created - Next.js, React, Tailwind CSS, Lucide icons)
- `ecommerce-app/frontend/next.config.js` (Created - Unsplash image domains config)
- `ecommerce-app/frontend/tailwind.config.js` (Created - Custom styling tokens)
- `ecommerce-app/frontend/postcss.config.js` (Created - PostCSS configuration)
- `ecommerce-app/frontend/app/globals.css` (Created - Tailwind directives and custom scrollbars)
- `ecommerce-app/frontend/app/layout.js` (Created - Providers, global header, drawer, toast, footer)
- `ecommerce-app/frontend/app/page.js` (Created - Hero banner, category pills, faceted search, 100-product grid)
- `ecommerce-app/frontend/app/product/[id]/page.js` (Created - Gallery, specs, review submission form, related items)
- `ecommerce-app/frontend/app/cart/page.js` (Created - Full cart breakdown and coupon validation)
- `ecommerce-app/frontend/app/checkout/page.js` (Created - Shipping, delivery method, payment, and order submission)
- `ecommerce-app/frontend/app/order-confirmation/[id]/page.js` (Created - Receipt and 4-step timeline tracker)
- `ecommerce-app/frontend/app/wishlist/page.js` (Created - Wishlist manager with move-to-cart)
- `ecommerce-app/frontend/app/orders/page.js` (Created - Live order status lookup)
- `ecommerce-app/frontend/components/Navbar.js` (Created - Live predictive search, badge counters, navigation)
- `ecommerce-app/frontend/components/Footer.js` (Created - Trust pillars, newsletter discount, legal links)
- `ecommerce-app/frontend/components/ProductCard.js` (Created - Hover zoom, urgency badges, rating, wishlist toggle)
- `ecommerce-app/frontend/components/CartDrawer.js` (Created - Slide-over drawer with free shipping progress bar)
- `ecommerce-app/frontend/components/FilterSidebar.js` (Created - Categories, price slider, rating, stock filters)
- `ecommerce-app/frontend/components/Toast.js` (Created - Non-intrusive notification alerts)
- `ecommerce-app/frontend/context/CartContext.js` (Created - Cart state & coupon calculation engine)
- `ecommerce-app/frontend/context/WishlistContext.js` (Created - Wishlist persistence)
- `ecommerce-app/start.bat` (Created - One-click CMD launcher)
- `ecommerce-app/start.ps1` (Created - One-click PowerShell launcher)
- `ecommerce-app/README.md` (Created - Comprehensive technical documentation and API reference)

### Verification & Quality Assurance
- **Database Seeder**: `node ecommerce-app/backend/src/db/seed.js` &rarr; 100 products, 8 categories, 4 coupons, and reviews successfully inserted into SQLite.
- **SQLite Data Integrity Verification**: Queried product counts, category groupings, and JSON fields via in-process SQLite driver with zero defects.
- **Frontend Production Build**: `npm run build` in `ecommerce-app/frontend/` &rarr; **Compiled successfully with 0 errors across all 8 static and dynamic routes**.

### Next Planned Task (Awaiting User Permission):
- [ ] Task ID: Standalone live testing or additional custom feature extensions upon request.


---

## [Task-12] - Integration of Embedded AI Shopping & Support Assistant
**Timestamp:** 2026-11-02 18:57:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Embed an intelligent AI Assistant directly into the full-stack e-commerce site to assist customers with grounded product recommendations, instant order lookup, discount discovery, and return policy answers.
- Ensure the AI engine is deterministic, responsive, and grounded strictly in the 100 SQLite products, active orders, and coupons database.

### Architectural Boundaries & Modularity
- **Backend AI Engine (`POST /api/ai/chat`) in `ecommerce-app/backend/src/server.js`**:
  - Semantic synonym expansion and entity extraction (price constraints, categories, brands, order references `ORD-...`, coupon queries).
  - Queries SQLite database in real time for relevant items, recalculating availability and ratings.
  - Returns structured textual explanations, actionable suggestion pills, order tracking objects, and enriched product recommendation arrays.
- **Frontend AI Widget (`ecommerce-app/frontend/components/AIAssistant.js`)**:
  - Floating action trigger with shimmering indicator and notification ping.
  - Full-featured chat drawer with starter conversation prompts, quick-reply pills, direct order tracking cards, and interactive product recommendation cards with one-click **"Add to Cart"** functionality.
  - Injected globally via `ecommerce-app/frontend/app/layout.js`.

### Files Touched
- `ecommerce-app/backend/src/server.js` (Modified - Added `POST /api/ai/chat` endpoint with NLU & SQLite grounding)
- `ecommerce-app/frontend/components/AIAssistant.js` (Created - Interactive floating AI Assistant widget)
- `ecommerce-app/frontend/app/layout.js` (Modified - Embedded `<AIAssistant />` globally)

### Verification & Quality Assurance
- Integration tests executed against `http://localhost:5000/api/ai/chat`:
  - `Find me espresso and coffee makers`: Successfully returned `BaristaPro Precision Espresso Machine`, `AuraBrew Kettle`, and `ColdBrew Pitcher`.
  - `What discount coupons do you have?`: Returned verified active codes `WELCOME10`, `SAVE20`, `SUPER30`, `FLASH50`.
  - `What is your return policy?`: Returned 30-day money-back guarantee, free shipping over $50, and 2-year warranty details.
  - `where is ORD-20261102-4821`: Looked up order in SQLite database and formatted status card.
- Frontend compilation & delivery: `http://localhost:3000` rendered with the AI assistant widget.

### Next Planned Task (Awaiting User Permission):
- [x] Task ID: Task-13: Master Control Dashboard Phase 1: Persistence & Row-Level Security (RLS)


---

## [Task-13] - Master Control Dashboard Phase 1: Persistence & Row-Level Security (RLS)
**Timestamp:** 2026-11-03 13:13:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement Component 1 of the Master Control Dashboard per approved Implementation Plan (v4):
  - Database schema definition using Alembic migrations with strict PostgreSQL 16 Row-Level Security (RLS) policies.
  - Multi-tenant data isolation: all tenant tables isolated using `tenant_isolation_policy` bound to `current_setting('app.tenant_id', true)` and `FORCE ROW LEVEL SECURITY`.
  - Principle of least privilege: application role `novaretail_app` granted standard CRUD on data tables, but strictly restricted to `INSERT` and `SELECT` only on `audit_events` (immutable audit trail).
  - Concrete PostgreSQL repositories behind existing ports (`OrderPort`, `CatalogPort`, `RefundPort`) replacing in-memory mocks.

### Architectural Boundaries & Modularity
- **Alembic Configuration (`support-assistant/alembic.ini`, `support-assistant/alembic/`)**:
  - `versions/001_core_and_rls.py`: DDL defining `tenants`, `staff_users`, `staff_tenant_memberships`, `staff_sessions`, `tenant_policy_configs`, `refund_requests`, `audit_events`, `conversation_sessions`, `conversation_turns`, `turn_raw`, `spend_ledger`, `escalations`, `knowledge_versions`, `knowledge_chunks`, `knowledge_version_chunks`, `ingestion_jobs`.
  - Migration helper applying RLS across all 13 tenant-scoped tables (`ENABLE` + `FORCE` + `tenant_isolation_policy`).
  - Partial unique index on `refund_requests (tenant_id, order_id, item_ref) WHERE state IN ('pending_approval', 'approved', 'processed')` preventing duplicate concurrent refunds.
  - Partial unique index on `ingestion_jobs (tenant_id, source_type) WHERE status IN ('queued', 'running')` enforcing single active ingestion job per tenant.
- **Database Session Manager (`support-assistant/db/session.py`, `support-assistant/db/models.py`)**:
  - Async & Sync engines supporting PostgreSQL (and SQLite in-memory fallback for fast isolated tests).
  - `get_async_session(tenant_id: str)` automatically sets `SELECT set_config('app.tenant_id', :tenant_id, true)` in the transaction.
- **Postgres Adapters (`support-assistant/adapters/postgres/`)**:
  - `order_repository.py`: implements `OrderPort` with customer ownership checks and shipping tracking timeline.
  - `catalog_repository.py`: implements `CatalogPort` with hybrid product lookup, live pricing, specifications, and filtered RAG on `(tenant_id, product_id)`.
  - `refund_repository.py`: implements `RefundPort` with idempotency deduplication, auto-refund limit routing (₹2,000 threshold), and staff decision recording.

### Files Touched
- `support-assistant/alembic.ini` (Created)
- `support-assistant/alembic/env.py` (Created)
- `support-assistant/alembic/script.py.mako` (Created)
- `support-assistant/alembic/versions/001_core_and_rls.py` (Created)
- `support-assistant/db/models.py` (Created)
- `support-assistant/db/session.py` (Created)
- `support-assistant/adapters/postgres/__init__.py` (Created)
- `support-assistant/adapters/postgres/order_repository.py` (Created)
- `support-assistant/adapters/postgres/catalog_repository.py` (Created)
- `support-assistant/adapters/postgres/refund_repository.py` (Created)
- `support-assistant/tests/test_alembic_and_rls.py` (Created)

### Verification & Quality Assurance
- Automated tests executed:
  - `python -m unittest support-assistant/tests/test_alembic_and_rls.py`:
    - `test_alembic_revisions_and_heads`: Verified Alembic recognizes `001_core_and_rls` as current head.
    - `test_offline_sql_generation_contains_all_rls_and_security_controls`: Verified DDL generation for all 16 tables, 2 partial unique indexes, RLS enablement, force RLS, tenant isolation policy, and `novaretail_app` role privilege restriction on `audit_events`.
    - `test_offline_downgrade_sql_generation`: Verified clean rollback SQL dropping RLS policies, unforcing RLS, and dropping tables in reverse dependency order.
    - `test_order_repository_and_tracking`: Verified ownership enforcement, customer authorization, and multi-stage tracking generation.
    - `test_refund_repository_idempotency_and_routing`: Verified auto-refund for <= ₹2,000, escalation routing to `pending_approval` for > ₹2,000, idempotency key deduplication, and staff decision recording.
    - `test_catalog_repository_search_and_specs`: Verified product lookup by alias, specs query, live price retrieval, and category filtering.
    - Outcome: **6/6 passed in 0.414s**.
  - Full Regression Test:
    - Command: `python -m unittest discover -s support-assistant/tests`
    - Outcome: **102/102 passed in 0.788s (0 regressions)**.

### Git Commit
- `5c4c2c9 feat(db): add alembic migrations with postgresql rls and adapters`

### Next Planned Task (Awaiting User Permission):
- [x] Task ID: Task-14: Master Control Dashboard Phase 2: Staff Auth, Approvals & Payment Outbox


---

## [Task-14] - Master Control Dashboard Phase 2: Staff Auth, Approvals & Payment Outbox
**Timestamp:** 2026-11-03 13:30:30 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement Component 2 and Component 3 of the Master Control Dashboard per approved Implementation Plan (v4):
  - Spec 15.1.8 Staff Identity & RBAC: per-person accounts (`staff_users`), Argon2id hashing, RFC 6238 TOTP MFA, opaque server-side sessions in PostgreSQL (`staff_sessions`), double-submit CSRF, step-up authentication (5-minute TTL), and role separation (`executive`, `manager`, `admin`).
  - R3 & Spec 10 Atomic Single-Transaction Approval: conditional SQL `UPDATE ... WHERE refund_id=:id AND state='pending_approval'` combined with `audit_events` insert in a single transaction, preventing check-then-act races and double approvals.
  - Approved Rows Outbox Worker: daemon leasing approved refunds with `FOR UPDATE SKIP LOCKED` and 120s lease timeout, idempotency key reconciliation on payment timeout, and customer notification dispatch.

### Architectural Boundaries & Modularity
- **Staff Auth & Session Service (`support-assistant/services/dashboard_api/auth.py`, `dependencies.py`)**:
  - Constant-time Argon2id password verification and pyotp TOTP MFA.
  - Server-side session store with `HttpOnly`, `SameSite=Strict` cookie and double-submit CSRF token.
  - Step-up re-authentication endpoint for high-risk operations (refunds > ₹5,000, policy limit changes, PII unmasking).
  - RBAC dependency enforcing strict role boundaries (`admin` cannot approve refunds or read conversations; `executive` cannot change money rules or unmask PII).
- **Atomic Refund State Machine (`support-assistant/core/refund_state_machine.py`)**:
  - Single-transaction atomic approval and rejection.
  - Request-time return window evaluation (prevents queue delays from unfairly rejecting customer refunds).
  - Step-up validation for refunds > ₹5,000.
- **Payment Outbox Worker Daemon (`support-assistant/services/support_desk/outbox_worker.py`)**:
  - Background worker leasing approved refunds via `FOR UPDATE SKIP LOCKED`.
  - Payment dispatch with idempotency key. Ambiguous network timeout triggers status lookup before retry; never blindly marks failed.
  - Channel notification with WhatsApp 24-hour window template guard.

### Files Touched
- `support-assistant/services/dashboard_api/__init__.py` (Created)
- `support-assistant/services/dashboard_api/auth.py` (Created)
- `support-assistant/services/dashboard_api/dependencies.py` (Created)
- `support-assistant/core/refund_state_machine.py` (Created)
- `support-assistant/services/support_desk/outbox_worker.py` (Created)
- `support-assistant/tests/test_staff_auth_mfa_sessions.py` (Created)
- `support-assistant/tests/test_refund_concurrency_race.py` (Created)
- `support-assistant/tests/test_outbox_worker_and_reconciliation.py` (Created)

### Verification & Quality Assurance
- Automated tests executed:
  - `python -m unittest support-assistant/tests/test_staff_auth_mfa_sessions.py`:
    - Argon2id password verification, TOTP validation, full login & MFA handshake, cookie generation, CSRF rejection, and role matrix separation (Admin blocked from refunds; Executive blocked from money rules; Manager step-up validated). Outcome: **4/4 passed**.
  - `python -m unittest support-assistant/tests/test_refund_concurrency_race.py`:
    - Verified single-transaction approval and audit insertion.
    - Double-approve concurrency race: 10 concurrent requests executed against the exact same refund. Result: Exactly 1 approval succeeded (200 OK) and exactly 9 failed with 409 Conflict. Exactly 1 audit record written.
    - Step-up requirement for refunds > ₹5,000 verified. Outcome: **3/3 passed**.
  - `python -m unittest support-assistant/tests/test_outbox_worker_and_reconciliation.py`:
    - Verified lease acquisition with 120s timeout.
    - Verified recovery from simulated worker crash via lease expiration.
    - Verified network timeout on payment API calls `query_payment_status` and backs off with retry count without marking `failed`.
    - Verified WhatsApp notifications outside 24h window select pre-approved Meta template. Outcome: **4/4 passed**.
  - Full Regression Suite:
    - Command: `python -m unittest discover -s support-assistant/tests`
    - Outcome: **113/113 passed in 1.285s (0 regressions)**.

### Git Commit
- `a15b094 feat(auth,refunds): implement staff auth, rbac, atomic refund approvals and payment outbox worker`

### Next Planned Task (Awaiting User Permission):
- [x] Task ID: Task-15: Master Control Dashboard Phase 3: Turn Recording, R5 Trace & R4 Spend Hot-Path


---

## [Task-15] - Master Control Dashboard Phase 3: Turn Recording, R5 Trace & R4 Spend Hot-Path
**Timestamp:** 2026-11-03 14:07:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement Component 4 of the Master Control Dashboard per approved Implementation Plan (v4):
  - Spec 14.1 & R5 Full Trace Persistence: every conversation turn recorded in `conversation_turns` with all required audit columns (masked prompt/completion, intent, latency, tokens, tool calls JSON, grounding score).
  - DPDP compliance: transcripts masked by default; unmasked raw text stored in `turn_raw` with strict Manager-only + Step-Up + Audited access.
  - R4 Spend Ledger & Hot-Path Cap Enforcement: token accounting in `spend_ledger`; chat worker enforces daily (₹2,500) and monthly (₹50,000) caps *before* calling the LLM, transitioning to fixed deterministic menus and human handoff when capped.
  - Dashboard Conversations & Reports APIs: endpoints for conversation list, turn trace inspection, PII unmasking, and spend/deflection reporting.

### Architectural Boundaries & Modularity
- **Worker Turn & Spend Orchestration (`support-assistant/services/worker/orchestrator.py`, `spend_manager.py`)**:
  - `SpendManager`: computes INR costs per model call, checks daily/monthly caps against `tenants` limits, and emits structured alerts at 80% cap.
  - Turn recorder: writes masked data to `conversation_turns`, raw data to `turn_raw`, and token costs to `spend_ledger` in database.
- **Conversations API (`support-assistant/services/dashboard_api/conversations.py`)**:
  - Filtered conversation listing.
  - Audited masked transcript view.
  - Audited Spec 14.1 trace viewer.
  - Manager-only + Step-up PII unmask workflow reading from `turn_raw` and logging audit events.
- **Reports API (`support-assistant/services/dashboard_api/reports.py`)**:
  - Spend meters, deflection rate, p50/p95 latency metrics, and cost per conversation.

### Files Touched
- `support-assistant/services/worker/spend_manager.py` (Created)
- `support-assistant/services/worker/turn_recorder.py` (Created)
- `support-assistant/services/worker/orchestrator.py` (Modified)
- `support-assistant/services/dashboard_api/conversations.py` (Created)
- `support-assistant/services/dashboard_api/reports.py` (Created)
- `support-assistant/tests/test_r5_trace_and_unmask.py` (Created)
- `support-assistant/tests/test_spend_ledger_and_cap_gate.py` (Created)
- `support-assistant/tests/test_staff_auth_mfa_sessions.py` (Modified - isolated step-up cache)
- `support-assistant/tests/test_worker_orchestrator.py` (Modified - driven with asyncio loop)

### Verification & Quality Assurance
- Automated tests executed:
  - `python -m unittest support-assistant/tests/test_r5_trace_and_unmask.py`:
    - Verified all Spec 14.1 trace columns populated on turn record.
    - Verified DPDP scrubbing of phones and emails in `user_input_masked`.
    - Verified audited transcript and turn trace reads.
    - Verified Manager-only + Step-up unmask workflow: Executive blocked with 403; Manager without step-up blocked with 403; Manager with step-up succeeds and writes immutable audit record. Outcome: **3/3 passed**.
  - `python -m unittest support-assistant/tests/test_spend_ledger_and_cap_gate.py`:
    - Verified INR token cost calculation for Llama 3 70B and 8B.
    - Verified hot-path spend cap gate: daily cap of ₹2,500 skips LLM, returns deterministic menu, routes to handoff.
    - Verified monthly 95% cap gate.
    - Verified Reports API spend meters and customer metrics. Outcome: **3/3 passed**.
  - Full Regression Suite:
    - Command: `python -m unittest discover -s support-assistant/tests`
    - Outcome: **119/119 passed in 7.617s (0 regressions)**.

### Git Commit
- `3852633 feat(tracing,spend): implement spec 14.1 turn recording, r5 trace viewer, and r4 hot-path spend cap enforcement`

### Next Planned Task (Awaiting User Permission):
- [x] Task ID: Task-16: Master Control Dashboard Phase 4: Escalations Queue & Bot Silencing


---

## [Task-16] - Master Control Dashboard Phase 4: Escalations Queue & Bot Silencing
**Timestamp:** 2026-11-03 14:18:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement Component 5 of the Master Control Dashboard per approved Implementation Plan (v4):
  - Spec 5.2 & 16.4 Human Escalation Queue: dedicated `escalations` table for customer tickets requiring human intervention.
  - Atomic Claim Race Protection: single-transaction conditional update `UPDATE escalations SET state='assigned', assigned_to=:staff WHERE esc_id=:id AND state='open'` with simultaneous audit logging.
  - Human Takeover Bot Silencing: when an escalation ticket is `open` or `assigned`, the chat worker silences the AI bot completely, making zero model calls and responding with a fixed support template.

### Architectural Boundaries & Modularity
- **Escalations API (`support-assistant/services/dashboard_api/escalations.py`)**:
  - Filtered ticket listing (`open`, `assigned`, `resolved`) with wait times.
  - Concurrency-safe atomic ticket claim endpoint returning 409 Conflict if already claimed.
  - Ticket resolution endpoint with mandatory documentation note ($\ge 10$ chars) and audit logging.
- **Bot Silencing Gate in Orchestrator (`support-assistant/services/worker/orchestrator.py`, `escalation_guard.py`)**:
  - Pre-LLM check on active escalation status for the customer session.
  - Bypasses LLM when ticket is active, preserving conversation context for human executive.

### Files Touched
- `support-assistant/services/dashboard_api/escalations.py` (Created)
- `support-assistant/services/worker/escalation_guard.py` (Created)
- `support-assistant/services/worker/orchestrator.py` (Modified)
- `support-assistant/tests/test_escalations_and_bot_silencing.py` (Created)

### Verification & Quality Assurance
- Automated tests executed:
  - `python -m unittest support-assistant/tests/test_escalations_and_bot_silencing.py`:
    - Verified escalations listing, filtering by state/priority, and wait time calculation.
    - Verified atomic claim race: 5 concurrent executive claim requests; exactly 1 succeeded (200 OK) and 4 received 409 Conflict. Exactly 1 claim audit event recorded.
    - Verified bot silencing: customer messages during active escalation return fixed human takeover template and completely suppress model calls.
    - Verified resolution workflow: resolving ticket with mandatory $\ge 10$-character note updates state to `resolved`, updates conversation handoff state, and clears silencing. Outcome: **4/4 passed in 0.908s**.
  - Full Regression Suite:
    - Command: `python -m unittest discover -s support-assistant/tests`
    - Outcome: **123/123 passed (0 regressions)**.

### Git Commit
- `a4d4e2e feat(escalations): implement escalations queue, atomic claim race protection, and bot silencing gate`

### Next Planned Task (Awaiting User Permission):
- [x] Task ID: Task-17: Master Control Dashboard Phase 5: Knowledge Version Manifest & Eval Gate


---

## [Task-17] - Master Control Dashboard Phase 5: Knowledge Version Manifest & Eval Gate
**Timestamp:** 2026-11-03 14:35:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement Component 6 of the Master Control Dashboard per approved Implementation Plan (v4):
  - Spec 5.3, 16.6 & 17 Knowledge Staging & Eval Gate: replace brittle in-place chunk updates with an immutable, content-addressed version manifest (`knowledge_versions`, `knowledge_chunks`, `knowledge_version_chunks`).
  - Safe Policy Ingestion: PDF/MD/TXT clause extraction with visual clause preview and confirmed policy values form (`return_window_days`, `excluded_categories`, `auto_refund_limit_inr`).
  - Safe Catalog Ingestion & Deletion Guard: background ingestion job tracking with partial unique index (1 active job per tenant) and automatic abort guard if catalog items drop $> 20\%$.
  - Pre-Promotion Eval Gate: automated pre-promotion eval checking deterministic rules (100% pass) and fuzzy QA ($\ge 90\%$), Manager override with step-up MFA and written justification, atomic pointer promotion (`tenants.active_policy_version`), cache clearing, and one-click rollback.

### Architectural Boundaries & Modularity
- **Knowledge Manifest Engine (`support-assistant/ingestion/manifest_engine.py`)**:
  - Content-addressing: `sha256(tenant_id|source|product_id|text|model|chunker)`. Deduplicates identical chunks across versions.
  - Safe policy extraction rejecting unmapped glyph ratios $> 30\%$ or scanned PDFs without text layers.
  - Draft policy creation with clause preview.
  - Catalog ingest runner with $>20\%$ drop protection.
  - Automated eval runner evaluating draft versions against confirmed policy expectations.
  - Single-transaction pointer flip and one-click rollback.
- **Knowledge API Router (`support-assistant/services/dashboard_api/knowledge.py`)**:
  - Endpoints: `POST /policy/upload`, `POST /policy/draft`, `POST /catalog/sync`, `GET /jobs/{job_id}`, `GET /versions`, `GET /versions/{version_id}`, `POST /versions/{version_id}/eval`, `POST /versions/{version_id}/promote`, `POST /rollback`.
- **Cache Invalidation (`support-assistant/core/router/cache.py`)**:
  - Added `invalidate_tenant(tenant_id)` to flush tenant-scoped knowledge and product caches upon version promotion or rollback.

### Files Touched
- `support-assistant/ingestion/manifest_engine.py` (Created)
- `support-assistant/services/dashboard_api/knowledge.py` (Created)
- `support-assistant/core/router/cache.py` (Modified - added `invalidate_tenant`)
- `support-assistant/requirements.txt` (Modified - added `pypdf>=5.0.0`)
- `support-assistant/tests/test_knowledge_manifest_and_eval_gate.py` (Created)

### Verification & Quality Assurance
- Automated Test Suite:
  - `python -m unittest support-assistant/tests/test_knowledge_manifest_and_eval_gate.py`:
    - `test_content_addressed_chunk_deduplication`: Verified deterministic chunk hashing, whitespace normalization, and database chunk reuse across drafts.
    - `test_policy_upload_markdown_and_glyph_rejection`: Verified clause preview generation for Markdown, rejection of documents with $>30\%$ corrupted glyphs, rejection of empty files, and rejection of scanned/empty PDFs.
    - `test_confirmed_policy_values_form_and_draft_creation`: Verified draft version manifest captures confirmed values (`return_window_days=45`, `auto_refund_limit_inr=3000`).
    - `test_catalog_ingestion_and_deletion_guard_abort`: Verified $30\%$ catalog drop aborts sync, fails job, and protects existing active index. Verified $10\%$ drop completes successfully.
    - `test_active_ingestion_job_concurrency_conflict`: Verified 409 Conflict when attempting to start an ingestion job while one is already running.
    - `test_pre_promotion_eval_gate_and_manager_override`: Verified eval gate blocks failing version from promotion; Executive blocked with 403; Manager without step-up blocked with 403; Manager without reason blocked with 400; Manager with step-up and written justification succeeds, flips pointer, and logs `knowledge_promotion_override` audit event.
    - `test_atomic_promotion_and_one_click_rollback`: Verified promotion of v1, promotion of v2 archiving v1, and rollback restoring v1, flipping `tenants.active_policy_version`, and recording audit event.
    - Outcome: **7/7 passed in 1.961s**.
- Full Regression Test:
  - Command: `python -m unittest discover -s support-assistant/tests`
  - Outcome: **130/130 passed in 18.015s (0 regressions)**.

### Git Commit
- `9c0d017 feat(knowledge): implement knowledge version manifest, clause preview, deletion guard, and eval gate`

### Next Planned Task (Awaiting User Permission):
- [x] Task ID: Task-18: Master Control Dashboard Phase 6: Website Widget (Spec 16.1, 16.2) & React Dashboard Frontend

---

## [Task-18] - Master Control Dashboard Phase 6: Website Widget (Spec 16.1, 16.2) & React Dashboard Frontend
**Timestamp:** 2026-11-03 14:48:00 IST  
**Status:** COMPLETED & VERIFIED  

### Objective & Rationale ("Why")
- Implement Components 7 & 8 of the Master Control Dashboard per approved Implementation Plan (v4):
  - Spec 16.1 & 16.2 Embeddable Website Widget:
    - Open Shadow DOM (`element.attachShadow({ mode: 'open' })`) for full style isolation from host stylesheets.
    - Strict server-side origin enforcement: Gateway validates `Origin`/`Referer` headers against `tenants.widget_origins` on `/chat/*` and `/auth/otp/*`.
    - Dynamic token refresh: calls `data-get-token` callback function dynamically before requests.
    - Zero `innerHTML` injection: text rendering strictly via `textContent` to prevent DOM XSS vulnerabilities.
  - Spec 15.1.8 Master Control Dashboard React Frontend (`master-dashboard/`):
    - Modern React SPA built with Vite.
    - Auth & RBAC State (`AuthContext.jsx`): handles Argon2id + TOTP MFA authentication, double-submit CSRF with `X-CSRF-Token`, and role-based permissions (`executive`, `manager`, `admin`).
    - Dedicated management views:
      - `RefundsPage.jsx`: Concurrency-safe approvals queue, step-up MFA challenge for refunds $> ₹5,000$, and real-time status transitions.
      - `ConversationsPage.jsx`: Masked dialogue transcript viewer with DPDP-compliant PII masking and Manager-only step-up unmasking, plus Spec 14.1 trace viewer.
      - `EscalationsPage.jsx`: Real-time ticket queue with wait time calculation and atomic claim race protection.
      - `KnowledgePage.jsx`: Policy upload, clause preview, confirmed policy values form, automated eval runner, atomic pointer promotion, and one-click rollback.
      - `ReportsPage.jsx`: R4 spend ledger visualizer, daily (₹2,500) and monthly (₹50,000) spend meters, deflection rate, and p50/p95 latency metrics.
      - `StaffAdminPage.jsx`: Admin-only staff account management, session revocation, and tenant role administration.

### Architectural Boundaries & Modularity
- **Embeddable Widget (`support-assistant/static/widget/v1/widget.js`)**:
  - Independent Web Component / script attachment with Open Shadow DOM encapsulation.
  - Communication over Fetch API to Gateway `/chat/messages` and `/auth/otp/*`.
- **Gateway Server-Side Origin Guard (`support-assistant/services/assistant_api/gateway_app.py`)**:
  - Middleware/handler checking `Origin` or `Referer` against `tenants.widget_origins`. Rejects unauthorized origins with 403 Forbidden.
- **Master Control Dashboard Frontend (`master-dashboard/`)**:
  - Modular React components and pages with clean API client layer (`api/client.js`).
  - HttpOnly session cookie transmission with double-submit CSRF headers.

### Files Touched
- `support-assistant/static/widget/v1/widget.js` (Created)
- `support-assistant/services/assistant_api/gateway_app.py` (Modified - origin enforcement & widget script serving)
- `support-assistant/tests/test_widget_security_and_cors.py` (Created)
- `master-dashboard/` (Created React application with Vite, components, and pages)

### Verification & Quality Assurance
- Automated Test Suite:
  - `python -m unittest support-assistant/tests/test_widget_security_and_cors.py`:
    - `test_widget_js_static_serving`: Verified Gateway serves `/widget/v1/widget.js` with `application/javascript; charset=utf-8`.
    - `test_server_side_origin_enforcement_allowed`: Verified request with `Origin: https://shop.novaretail.com` receives 200 OK.
    - `test_server_side_origin_enforcement_disallowed`: Verified request with `Origin: https://malicious-phishing-site.com` receives 403 Forbidden with descriptive detail.
    - `test_widget_script_security_and_shadow_dom_invariants`: Verified Open Shadow DOM encapsulation, zero innerHTML injection (`bubble.textContent = text`), and `data-get-token` callback invocation.
    - Outcome: **4/4 passed in 0.015s**.
- Frontend Build Verification:
  - `npm.cmd run build` inside `master-dashboard/`:
    - Output: `dist/index.html` (0.71 kB), `dist/assets/index-Cr97oOWT.css` (13.08 kB), `dist/assets/index-C_CaZ_O8.js` (243.49 kB).
    - Outcome: **Vite build succeeded in 534ms with 0 errors and 0 warnings**.
- Full Regression Test:
  - Command: `python -m unittest discover -s support-assistant/tests`
  - Outcome: **134/134 passed in 18.276s (0 regressions)**.

### Git Commit
- `a472228 feat(widget-and-frontend): implement Spec 16.1 Shadow DOM widget, gateway origin enforcement, and React Master Control Dashboard`

### Next Planned Task (Awaiting User Permission):
- [x] Task ID: Task-19: Master Control Dashboard Phase 7: Hardening & 10× Load Burst

---

## [Task-19] - Master Control Dashboard Phase 7: Hardening & 10× Load Burst
**Timestamp:** 2026-11-03 15:17:00 IST  
**Status:** COMPLETED & VERIFIED (FINAL PHASE)

### Objective & Rationale ("Why")
- Execute Phase 7 final milestone per approved Implementation Plan (v4):
  - Validate system behavior under simulated concurrent burst load ($10\times$ concurrency).
  - Gate Requirement: "No over-cap calls; queue drains cleanly after burst."
  - Verify hot-path daily ₹2,500 spend cap gate prevents token leaks under concurrent requests via in-flight budget reservations.
  - Verify refund outbox worker competition with multi-worker leases drains queue without double payment or deadlocks.
  - Verify multi-ticket escalations claiming race under concurrent supervisors guarantees exact single-winner semantics and consistent 409 Conflict responses.
  - Verify catalog sync concurrency locking prevents overlapping index builds.

### Architectural Boundaries & Modularity
- **Burst Test Suite (`support-assistant/tests/test_hardening_and_burst.py`)**:
  - `test_spend_cap_gate_under_concurrent_burst`: 15 concurrent turns arriving at ₹2,490 daily spend; verifies exactly 1 LLM call executed, 14 gated with `route_type="spend_capped"` and `model_used="spend-cap-gate"`.
  - `test_outbox_queue_drain_under_concurrent_worker_competition`: 15 approved refunds drained by 3 concurrent workers in parallel; verifies exactly 15 payments, zero duplicates, and clean queue drain.
  - `test_escalations_multi_ticket_concurrent_claiming_burst`: 5 tickets, 15 concurrent supervisor claims (3 per ticket); verifies exactly 5 winners (200 OK), 10 conflicts (409 Conflict), and 5 audit events.
  - `test_ingestion_sync_lock_under_burst`: 4 concurrent sync requests while a job is active; verifies all 4 rejected with 409 Conflict, and subsequent request succeeds with 200 OK.
- **Worker Infrastructure Updates**:
  - `services/worker/spend_manager.py`: Added in-flight spend reservation (`reserve_in_flight`, `release_reservation`) inside `is_spend_capped()` to prevent TOCTOU concurrency race conditions where simultaneous requests slip through before logging turn spend.
  - `services/worker/orchestrator.py`: Integrated reservation lifecycle around model dispatch and turn spend recording.
  - `services/support_desk/outbox_worker.py`: Added `.execution_options(synchronize_session=False)` to lease update statements to prevent offset-naive datetime comparisons in SQLite, and appended `uuid.uuid4().hex[:8]` to outbox audit event IDs to eliminate uniqueness collisions during multi-worker execution.

### Files Touched
- `support-assistant/tests/test_hardening_and_burst.py` (Created)
- `support-assistant/services/support_desk/outbox_worker.py` (Modified - unique audit event IDs & synchronize_session=False)
- `support-assistant/services/worker/orchestrator.py` (Modified - spend reservation lifecycle handling)
- `support-assistant/services/worker/spend_manager.py` (Modified - atomic in-flight spend reservation & release)

### Verification & Quality Assurance
- Automated Burst Test Suite:
  - Command: `python -m unittest support-assistant/tests/test_hardening_and_burst.py`
  - Outcome: **4/4 passed in 5.352s (100.0%)**.
- Full Project Regression Suite:
  - Command: `python -m unittest discover -s support-assistant/tests`
  - Outcome: **138/138 passed in 24.859s (0 failures, 0 errors across 17 test suites)**.
- Invariants Confirmed:
  - Zero over-cap calls under concurrency burst.
  - Zero duplicate refund disbursements under multi-worker lease competition.
  - Exact single-winner ticket claims with audited supervisory ownership.
  - Zero overlapping ingestion jobs.

### Git Commit
- `feat(hardening): add 10x burst load tests, spend reservation lock, and outbox multi-worker safety`

---

## Master Control Dashboard Project Completion: 100.0% (7 of 7 Phases Completed)

### All Master Control Dashboard Phases Fully Implemented & Verified:
1. `[Task-13]` Persistence & Row-Level Security (Alembic DDL, RLS, Postgres Port Adapters) (100%)
2. `[Task-14]` Staff Auth, Argon2id, TOTP MFA, Atomic Approvals & Outbox Worker (100%)
3. `[Task-15]` Turn Recording, Spec 14.1 Trace, Manager Unmask & R4 Spend Hot-Path (100%)
4. `[Task-16]` Escalations Queue & Human Takeover Bot-Silencing Gate (100%)
5. `[Task-17]` Knowledge Version Manifest, Clause Preview, Deletion Guard & Eval Gate (100%)
6. `[Task-18]` Spec 16.1 Shadow DOM Widget, Server-Side Origin Guard & React Dashboard Frontend (100%)
7. `[Task-19]` Concurrency Hardening & 10× Load Burst Testing (100%)







