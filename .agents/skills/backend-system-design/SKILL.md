---
name: backend-system-design
description: Design and review production backend systems, APIs, service boundaries, data models, reliability, security, and scaling tradeoffs.
license: MIT
---

# Backend and system design

Start from user and business requirements. Separate required behavior and quality attributes (availability, latency, consistency, privacy, cost, operability) from assumptions. State estimates and tradeoffs instead of presenting a single architecture as universally correct.

## System shape and boundaries

- Define domain ownership, trust boundaries, data flows, failure modes, and external dependencies before choosing services or infrastructure.
- Prefer a modular monolith until independent deployment, scaling, ownership, or failure isolation justify service boundaries. Avoid splitting by technical layer alone.
- Make synchronous versus asynchronous workflows explicit. For durable work, use a persistent queue/job model with idempotent handlers, bounded retries, dead-letter visibility, and observable lifecycle state.
- Design for partial failure: timeouts, bounded concurrency, backpressure, graceful degradation, and recovery procedures. Distinguish liveness from readiness and probe dependencies appropriately.
- Include authentication, authorization, tenant isolation, secret handling, auditability, and data retention in the design, not as follow-up patches.

## API design

- Model business resources and stable contracts; do not expose database tables as the public API. Document request/response schemas, error semantics, authorization, pagination, filtering, and version evolution.
- Use HTTP method/status semantics consistently. Define idempotency and safe retry behavior for mutations; use conditional requests or concurrency controls where lost updates matter.
- Bound request sizes and execution time. Make long-running work asynchronous with an accepted response and a status/result resource when a request cannot reliably finish within the request budget.
- Generate and validate OpenAPI contracts where they fit the stack. Keep compatibility checks aligned to actual client guarantees.
- Carry trace/correlation context across service boundaries without trusting user-supplied identity or tenant claims.

## Database design

- Model invariants and access patterns first. Choose normalized relational structures by default; denormalize only for measured read or ownership needs and define consistency/update behavior.
- Use explicit primary/foreign keys, appropriate nullability and constraints, deliberate indexes based on query plans, and bounded transactions. Avoid unbounded scans and N+1 access patterns.
- Enforce tenant/data access in the database query or policy boundary; do not rely on filtering after broad retrieval. Use least-privilege roles and reviewed migrations.
- Consider connection limits, pool sizing, locks, transaction isolation, backup/restore, retention, and migration rollback before production rollout.
- For Postgres, consult the linked Supabase-maintained guidance as a database-engine reference; its hosting assumptions are optional and must not be imported into unrelated stacks.

## Decision and review record

For material design choices, record the context, options, tradeoffs, chosen approach, and consequences in a short decision record. Review bottlenecks and reliability assumptions against workload estimates; do not add caching, sharding, microservices, or queues without a specific need.

## Primary references

- [Microsoft REST API design guidance](https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design): resource modeling, pagination, versioning, multitenancy, and contract design.
- [Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/): system patterns and distributed-system tradeoffs; use provider-neutral reasoning when Azure is not the target.
- [Supabase Postgres Best Practices](https://github.com/supabase/agent-skills/tree/main/skills/supabase-postgres-best-practices): Postgres schema, query, connection, security, and operations topics.
