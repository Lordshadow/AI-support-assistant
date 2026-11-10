---
name: mcp-tools-production
description: Production-grade Model Context Protocol (MCP) clients and servers, protocol lifecycle, stdio and Streamable HTTP transports, tool interface design, execution boundaries, and least-privilege security.
license: MIT
---

# Production-Grade MCP & Agent Tools Engineering

## Purpose & Scope
This skill provides standards for building, hosting, consuming, and securing tools via Anthropic's **Model Context Protocol (MCP)** and native function calling. It prevents context bloat, enforces sandboxed execution, and isolates trust boundaries.

---

## 1. MCP Architecture & Transport Standards

MCP establishes a standard JSON-RPC 2.0 protocol between AI agent hosts and tool/context servers.

```text
┌──────────────────────────────────────────────┐
│             Agent Host Runtime               │
│  - Prompt assembly & context management      │
│  - Progressive Tool Discovery Manager        │
│  - Security Membrane & Audit Logger          │
└──────────────┬───────────────────────────────┘
               │ 
       Transports (JSON-RPC 2.0)
       ├── Local: stdio (subprocess)
       └── Remote: Streamable HTTP
               │
┌──────────────▼───────────────────────────────┐
│              MCP Tool Server                 │
│  - Tools: List & Call Tool handlers          │
│  - Prompts: Reusable prompt templates        │
│  - Resources: Dynamic read-only context data │
└──────────────────────────────────────────────┘
```

### 1.1 Transport Selection
- Choose from transports supported by the current MCP specification and client/server SDK version. Prefer stdio for local process integration and Streamable HTTP for remote services; do not treat legacy HTTP+SSE as the default for new systems.
- For remote servers, use TLS and the authentication mechanism required by the host and deployment. Validate issuer, audience, scopes, and tenant authorization server-side; never treat a client-provided tenant identifier as trusted identity.

### 1.2 MCP Client Lifecycle
- Complete protocol initialization and capability negotiation before calling tools, reading resources, or using prompts. Gate optional operations on the negotiated capabilities.
- Handle notifications, cancellation, timeouts, and orderly shutdown according to the current SDK and transport.
- Keep server connections, credentials, capability state, and tenant context isolated. Do not expose one connection's tools or data in another user's context.
- Treat tool results and resource contents as untrusted input. Validate schemas and bound payload size before passing them to an LLM or downstream system.
- Classify protocol errors separately from tool-level errors. Retry only transient safe-to-repeat operations; mutations need idempotency or explicit confirmation semantics.

---

## 2. Progressive Tool Discovery (Preventing Context Bloat)

### 2.1 Progressive Discovery
Large tool catalogs can consume context and make selection harder. Use progressive discovery when the available schemas are large enough to impair selection or leave insufficient room for task context. Keep a concise, outcome-oriented index and load full schemas only when needed; a fixed percentage is not a universal threshold.

```python
from pydantic import BaseModel, Field

class ToolDescriptor(BaseModel):
    name: str
    description: str
    category: str

class SearchToolsInput(BaseModel):
    query: str = Field(description="Search term describing the action or information needed.")

async def search_tools(query: str, available_tools: list[ToolDescriptor]) -> list[dict]:
    """Dynamically returns full schemas of tools matching the agent's current intent."""
    # Matches via semantic embedding or BM25 keyword matching
    matched = [t for t in available_tools if query.lower() in t.name or query.lower() in t.description]
    return [get_full_tool_schema(t.name) for t in matched[:3]]
```

---

## 3. Tool Design Principles for AI Agents

LLMs reason differently than traditional API clients. Design tools as **agent interfaces**, not direct database CRUD mirrors:
1. **Outcome-Oriented Design:** Consolidate multi-step queries into goal-driven tools (e.g., `get_order_and_delivery_status` rather than separate `get_order`, `get_shipment`, and `get_carrier_eta`).
2. **Flatten Arguments:** Avoid deep, nested JSON objects. Use top-level strings, integers, and flat lists.
3. **Descriptive Docstrings & Constraints:** Specify exact formats (e.g., `"ISO 8601 YYYY-MM-DD"`, `"Phone in E.164 format"`).
4. **Token-Efficient Outputs:** Never return raw 5MB database dumps. Return compact, markdown or JSON-keyed facts.
5. **Actionable Error Messages:** When a tool fails, return an actionable remediation hint (e.g., `{"error": "ORDER_NOT_FOUND", "hint": "Check if order_id has prefix 'ORD-' or search by customer phone number"}`) so Claude can self-correct.

---

## 4. Execution Sandboxing & Resilience

Every tool call must run inside a deterministic execution wrapper with strict timeouts and error classification.

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class TransientToolError(Exception):
    """Network timeouts or 503 errors that are safe to retry."""
    pass

class PermanentToolError(Exception):
    """Validation or authorization failures that must not be retried."""
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=1.0, max=4.0),
    retry=retry_if_exception_type(TransientToolError)
)
async def sandboxed_tool_call(tool_func, args: dict, timeout_seconds: float = 5.0) -> dict:
    try:
        # Strict timeout guard
        return await asyncio.wait_for(tool_func(**args), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise TransientToolError("Tool execution timed out.")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {429, 502, 503, 504}:
            raise TransientToolError(f"Upstream provider unavailable: {exc.response.status_code}")
        raise PermanentToolError(f"Client error from upstream service: {exc.response.status_code}")
    except Exception as exc:
        return {"error": "EXECUTION_ERROR", "detail": str(exc)}
```

---

## 5. Security & Least Privilege Tiers (The Quarantine Pattern)

Prevent indirect prompt injection and unauthorized mutations by splitting agent execution into isolated tiers:

| Tier | Role | Allowed Tools | Mutation Access |
| :--- | :--- | :--- | :--- |
| **Reader Tier** | Ingests untrusted documents, customer emails, web pages | Read-only search, string filters | **FORBIDDEN** (No DB writes or refunds) |
| **Orchestrator Tier** | Reasons on sanitized data, drafts plans | State graph nodes, read-only MCP | **FORBIDDEN** (Generates action payloads only) |
| **Resolver / Actor Tier**| Executes financial or system mutations | Mutation tools (e.g., `initiate_refund`) | **GATED** (Requires verified OTP & HITL approval) |

## Primary references

- [Model Context Protocol specification](https://modelcontextprotocol.io/specification/): current protocol lifecycle, transports, client/server capabilities, and request behavior.
- [MCP server development skills](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/mcp-server-dev): implementation workflows for servers and packaging.
- [Anthropic tool design guidance](https://www.anthropic.com/engineering/building-effective-agents): tool selection and interface design principles. Apply them as design guidance, not protocol requirements.
