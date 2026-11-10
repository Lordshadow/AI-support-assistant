---
name: fastapi-agent-service
description: Production-grade FastAPI AI agent service patterns, async lifespan management, SSE streaming, client disconnection handling, background tasks, concurrency semaphores, and Claude integration.
license: MIT
---

# Production-Grade FastAPI AI Agent Service

Check the installed FastAPI, Pydantic, Python, and provider SDK versions before applying examples; APIs and model identifiers change. Treat snippets as architectural illustrations. Do not stream private reasoning or raw exception text to clients; expose user-safe statuses and error codes.

## Purpose & Scope
This skill provides production-grade architectural patterns, streaming protocols, concurrency controls, and lifecycle management for building high-concurrency, low-latency AI agent services using **FastAPI** and modern LLM runtimes (including Anthropic Claude).

---

## 1. Architectural Foundations

### 1.1 Decoupled Execution Model
Production AI agents perform multi-step reasoning, external tool calls, and vector lookups that take seconds to minutes. Synchronous blocking or unmanaged background threads will exhaust the event loop and drop client requests.

```text
┌─────────────────────────┐
│     Client / Browser    │
└───────────┬─────────────┘
            │ 1. POST /v1/agent/runs (SSE Stream or Job Token)
            ▼
┌────────────────────────────────────────────────────────┐
│               FastAPI Gateway Layer                    │
│  - Lifespan State (DB pools, Vector clients, MCP)      │
│  - Pydantic v2 Schema Validation                       │
│  - Correlation ID Middleware (X-Request-ID)            │
│  - Concurrency Semaphore & Rate Limiting               │
└───────────┬────────────────────────────────────────────┘
            │ 
    ┌───────┴────────────────────────┐
    │ Direct Streaming Route         │ Async Job Enqueue
    ▼                                ▼
┌──────────────────────┐   ┌──────────────────────────────┐
│  SSE Event Generator │   │ Task Broker (Redis/Arq/Celery│
│  - Token streaming   │   │ - Long-running workflows     │
│  - Disconnect guard  │   │ - Human-in-the-loop pauses   │
│  - Anthropic SDK     │   │ - Durable checkpoints        │
└──────────────────────┘   └──────────────────────────────┘
```

### 1.2 In-Process BackgroundTasks vs. Distributed Task Queues
- **FastAPI `BackgroundTasks`:** Strict usage boundary. Use *only* for non-critical, lightweight fire-and-forget post-processing (e.g., publishing audit logs, updating token usage metrics, firing analytics events). 
  - *Anti-Pattern:* Never run multi-turn agent execution loops in `BackgroundTasks`. If the Uvicorn worker restarts or scales down, in-flight state is lost.
- **Distributed Queues (Arq / Celery / Redis Streams / Temporal):** Mandatory for durable, long-running agent workflows, asynchronous multi-tool executions, and human-in-the-loop approval wait states.

---

## 2. Real-Time Streaming & Client Disconnections

### 2.1 Server-Sent Events (SSE) Protocol
SSE is the industry standard for LLM and agent outputs because communication is unidirectional (Server to Client), works over standard HTTP/2, handles auto-reconnection natively, and bypasses WebSocket proxy hurdles.

Standard Event Taxonomy:
- `event: metadata`: Trace ID, model identifier, timestamp.
- `event: thought`: Reasoning step or scratchpad output.
- `event: tool_call`: Tool invocation name, call ID, and sanitized arguments.
- `event: tool_result`: Tool execution outcome or error hint.
- `event: token`: Incremental text chunk for UI rendering.
- `event: complete`: Final execution summary, total tokens, and stop reason.
- `event: error`: Normalized error payload with user-safe message.

### 2.2 Client Disconnection & Task Cancellation
When a user closes their browser tab or navigates away, ongoing LLM calls must be immediately aborted to prevent burning API tokens and tying up compute.

```python
import asyncio
import json
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, Request, HTTPException, status
from sse_starlette.sse import EventSourceResponse
import anthropic

router = APIRouter(prefix="/v1/agent", tags=["Agent Streaming"])

async def stream_claude_agent(
    prompt: str,
    request: Request,
    client: anthropic.AsyncAnthropic
) -> AsyncGenerator[dict, None]:
    """Streams Claude agent events while rigorously monitoring client connection state."""
    yield {
        "event": "metadata",
        "data": json.dumps({"status": "starting", "model": "claude-3-7-sonnet-20250219"})
    }

    try:
        # Prompt caching + Anthropic streaming context
        async with client.messages.stream(
            model="claude-3-7-sonnet-20250219",
            max_tokens=4096,
            thinking={"type": "enabled", "budget_tokens": 1024},
            system=[
                {
                    "type": "text",
                    "text": "You are a production support assistant. Think carefully before answering.",
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for event in stream:
                # 1. Guard: Check if the client disconnected prematurely
                if await request.is_disconnected():
                    # Raising CancelledError immediately closes the streaming pipeline
                    raise asyncio.CancelledError("Client disconnected")

                if event.type == "thinking_delta":
                    yield {
                        "event": "thought",
                        "data": json.dumps({"delta": event.delta})
                    }
                elif event.type == "text_delta":
                    yield {
                        "event": "token",
                        "data": json.dumps({"delta": event.delta})
                    }

            # Final turn stats
            final_message = await stream.get_final_message()
            yield {
                "event": "complete",
                "data": json.dumps({
                    "usage": {
                        "input_tokens": final_message.usage.input_tokens,
                        "output_tokens": final_message.usage.output_tokens,
                        "cache_read_tokens": getattr(final_message.usage, "cache_read_input_tokens", 0)
                    },
                    "stop_reason": final_message.stop_reason
                })
            }

    except asyncio.CancelledError:
        # Graceful cleanup on client abort
        yield {
            "event": "error",
            "data": json.dumps({"code": "CLIENT_DISCONNECT", "detail": "Generation cancelled by client"})
        }
    except Exception as exc:
        yield {
            "event": "error",
            "data": json.dumps({"code": "AGENT_STREAM_ERROR", "detail": str(exc)})
        }

@router.post("/chat/stream")
async def chat_stream_endpoint(
    request: Request,
    payload: dict,
    client: anthropic.AsyncAnthropic = Depends(get_anthropic_client)
):
    prompt = payload.get("message", "").strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")
    
    return EventSourceResponse(
        stream_claude_agent(prompt=prompt, request=request, client=client),
        ping=15  # Keep-alive heartbeat ping every 15s to keep intermediaries open
    )
```

---

## 3. Lifespan Context & Resource Pooling

Never initialize database connections, vector store drivers, or HTTP clients inside route handlers. Use FastAPI's async `lifespan` context manager.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
import httpx
import anthropic

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Phase ---
    # 1. Shared HTTP client pool with HTTP/2 and keep-alive limits
    app.state.http_client = httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_keepalive_connections=50, max_connections=200)
    )
    
    # 2. Anthropic async client initialized with shared HTTP transport
    app.state.anthropic_client = anthropic.AsyncAnthropic(
        http_client=app.state.http_client,
        max_retries=3
    )
    
    # 3. Concurrency Semaphore (Limits simultaneous LLM streams to prevent OOM / rate exhaustion)
    app.state.agent_semaphore = asyncio.Semaphore(50)
    
    yield
    
    # --- Shutdown Phase ---
    # Graceful connection draining
    await app.state.http_client.aclose()

app = FastAPI(lifespan=lifespan)
```

---

## 4. Concurrency Guardrails & Timeouts

### 4.1 Strict Timeouts
Never invoke an LLM or tool without an explicit timeout boundary. Wrap network boundaries with `asyncio.wait_for`.

```python
async def execute_tool_with_timeout(tool_func, args: dict, timeout_seconds: float = 8.0):
    try:
        return await asyncio.wait_for(tool_func(**args), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return {"error": "TOOL_TIMEOUT", "message": f"Execution exceeded {timeout_seconds}s deadline."}
```

### 4.2 Semaphore Protection
Protect server capacity from burst traffic:
```python
async def acquire_agent_slot(request: Request):
    semaphore: asyncio.Semaphore = request.app.state.agent_semaphore
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=2.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Agent capacity saturated. Retry shortly.")
    try:
        yield
    finally:
        semaphore.release()
```

---

## 5. Structured Observability & Correlation Tracing

1. **Correlation Middleware:** Generate or propagate `X-Correlation-ID` on all incoming requests and attach to Python `contextvars`.
2. **Sanitized Error Handler:** Never leak raw stack traces, API keys, or internal database schemas to clients. Catch all unhandled exceptions at the root exception handler and emit a standardized JSON error envelope with the correlation ID.

## Primary references

- [FastAPI documentation](https://fastapi.tiangolo.com/): dependencies, lifespan, async behavior, and deployment.
- [Python asyncio documentation](https://docs.python.org/3/library/asyncio.html): cancellation, concurrency, timeouts, and task lifecycle.
