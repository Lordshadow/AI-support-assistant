---
name: python-production-engineering
description: Build and review production Python services and libraries, including typing, packaging, async I/O, reliability, and maintainable module boundaries.
license: MIT
---

# Python production engineering

Use the repository's supported Python version, dependency manager, formatting rules, and architecture. Confirm them before choosing syntax or adding dependencies. Prefer small, typed interfaces and explicit ownership over clever abstractions.

## Design and implementation

- Add type annotations to public interfaces. Use concrete domain types and narrow protocols where they clarify boundaries; avoid `Any` and unvalidated dictionaries spreading across layers.
- Validate untrusted input at boundaries, distinguish expected domain failures from infrastructure errors, and preserve useful exception context without exposing secrets or personal data.
- Keep modules cohesive. Separate transport, domain behavior, persistence, and external clients when those boundaries already exist or provide a real testing or change-isolation benefit.
- Use context managers for resource ownership. Make cleanup reliable on both success and failure; initialize shared clients and pools once per process lifecycle.
- Use immutable values where they simplify reasoning. Avoid hidden global mutable state and import-time network or filesystem effects.

## Async and concurrency

- Use `asyncio` for I/O-bound concurrent work when dependencies provide async APIs. Async functions must not perform blocking I/O or CPU-heavy work on the event loop; use an appropriate thread/process boundary or job system where needed.
- Bound fan-out, queues, connection pools, and in-flight work. Put explicit timeouts around network boundaries and retry only transient, safe-to-repeat operations with a cap and backoff.
- Propagate cancellation and shut down tasks cleanly. Do not swallow `CancelledError`; make mutation retries idempotent.
- Keep synchronous APIs synchronous unless async materially benefits the call path. Avoid mixing event-loop management into reusable library functions.

## Quality and operations

- Keep configuration external and validated at startup. Never log credentials, access tokens, raw customer messages, or unredacted provider payloads.
- Use structured logs with request/job correlation, meaningful metrics, and health checks for independently failing dependencies.
- Prefer deterministic unit tests for domain logic and integration tests at real persistence/network boundaries when requested by the task.
- Check the project's lint, type-check, and test commands before introducing new tools or patterns.

## Primary references

- [Python asyncio documentation](https://docs.python.org/3/library/asyncio.html): concurrency primitives and I/O-bound async work.
- [Python typing documentation](https://docs.python.org/3/library/typing.html): type-system features; confirm compatibility with the project's Python floor.
