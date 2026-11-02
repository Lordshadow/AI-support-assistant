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

## Project Completion Progress: 54.5% (6 / 11 Milestones Completed)

## Next Planned Task (Awaiting User Permission)
- **[Task-06] Worker Orchestrator & LLM Integration (Groq & NIM):**
  - Build the conversational agent loop and tool execution planning.
  - Implement look-alike disambiguation gate.
  - Integrate Groq API client with local mock engine fallback for zero-cost offline development.
