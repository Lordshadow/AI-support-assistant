# Workspace Skills (Vetted & Audited)

These skills provide structured engineering standards, operational protocols, and domain expertise aligned with this project's customer support assistant, RAG ingestion, evaluation pipelines, and master dashboard.

## Safety & Security Verification
Every skill in this directory has undergone static safety auditing:
- **100% Declarative**: Pure Markdown instructions without arbitrary execution scripts or unverified dependencies.
- **Zero Injections**: Screened against prompt overrides, hidden instructions, and delimiter escapes.
- **Privacy & Safety Preserving**: Built-in guardrails against PII leakage, unauthorized refunds, and destructive system commands.
- **Validated**: Formally checked and validated against the skill validator schema.

---

## Installed Skills Catalog

### 1. Production Agent Infrastructure & Backend Services
| Skill | Description | Location |
| :--- | :--- | :--- |
| **`fastapi-agent-service`** | Production-grade FastAPI AI agent service patterns, async lifespan management, SSE streaming, client disconnection handling, background tasks, and concurrency semaphores | [SKILL.md](./fastapi-agent-service/SKILL.md) |
| **`langchain-langgraph-runtime`** | Production-grade LangChain and LangGraph state graph architecture, persistent PostgreSQL checkpointers, human-in-the-loop interrupts, time-travel, and idempotent tool execution | [SKILL.md](./langchain-langgraph-runtime/SKILL.md) |
| **`production-grade-ai-agent`** | Deterministic execution membrane, deep trajectory tracing, HITL governance, evals, and auditability | [SKILL.md](./production-grade-ai-agent/SKILL.md) |
| **`python-production-engineering`** | Typed Python service/library design, async I/O, resource ownership, and operational reliability | [SKILL.md](./python-production-engineering/SKILL.md) |
| **`backend-system-design`** | Backend/system architecture, API contracts, service reliability, and relational database design | [SKILL.md](./backend-system-design/SKILL.md) |

### 1a. Web Application Engineering
| Skill | Description | Location |
| :--- | :--- | :--- |
| **`react-nextjs-engineering`** | Production React/Next.js performance, rendering boundaries, JavaScript, accessibility, and data fetching | [SKILL.md](./react-nextjs-engineering/SKILL.md) |

### 2. Retrieval, Vector Databases & Ingestion
| Skill | Description | Location |
| :--- | :--- | :--- |
| **`vectordb-hybrid-retrieval`** | Production-grade vector database engineering, pgvector and Qdrant optimization, hybrid search with Reciprocal Rank Fusion (RRF), cross-encoder re-ranking, HNSW index tuning, and multi-tenant isolation | [SKILL.md](./vectordb-hybrid-retrieval/SKILL.md) |
| **`rag-ingestion-engineering`** | Project-scoped production RAG ingestion, pgvector versioning, tenant filters, jobs, and evaluations | [SKILL.md](./rag-ingestion-engineering/SKILL.md) |

### 3. Model Context Protocol, Tools & Claude Integration
| Skill | Description | Location |
| :--- | :--- | :--- |
| **`mcp-tools-production`** | Production MCP clients and servers, protocol lifecycle, stdio and Streamable HTTP, tool design, and least-privilege security | [SKILL.md](./mcp-tools-production/SKILL.md) |
| **`claude-agent-engineering`** | Production-grade Claude agent and prompt engineering, XML tag architecture, prompt caching, extended thinking mode, tool-use calibration, and Anthropic API integration | [SKILL.md](./claude-agent-engineering/SKILL.md) |
| **`senior-prompt-engineer`** | Instruction architecture, CoT scaffolding, and few-shot calibration for SkillOpt | [SKILL.md](./senior-prompt-engineer/SKILL.md) |

### 4. Domain & User Experience
| Skill | Description | Location |
| :--- | :--- | :--- |
| **`customer-support-expert`** | Customer support ticket triage, de-escalation, policy enforcement, and resolution | [SKILL.md](./customer-support-expert/SKILL.md) |
| **`ui-ux-design-expert`** | Production-grade dashboard UI/UX design, teal glassmorphism design tokens, WCAG 2.1 AA accessibility, and ergonomics | [SKILL.md](./ui-ux-design-expert/SKILL.md) |

### 5. Quality, Governance & Debugging
| Skill | Description | Location |
| :--- | :--- | :--- |
| **`skill-security-auditor`** | Audit checklist to screen future external skills, plugins, and scripts before adoption | [SKILL.md](./skill-security-auditor/SKILL.md) |
| **`systematic-debugging`** | 4-phase root cause analysis protocol (reproduce → hypothesize → gather evidence → fix) | [SKILL.md](./systematic-debugging/SKILL.md) |
| **`senior-qa-engineer`** | Quality assurance, boundary testing, and adversarial red-teaming for agent policies | [SKILL.md](./senior-qa-engineer/SKILL.md) |
| **`task-logger`** | Standardized protocol for logging development progress, task execution rationale, and verification into logs.md | [SKILL.md](./task-logger/SKILL.md) |
