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

## Next Planned Task (Awaiting User Permission)
- **[Task-01] Core Domain Models & Ports:** Build the domain entities, abstract ports (`typing.Protocol`), and pure business rule engine in `support-assistant/core/`.
