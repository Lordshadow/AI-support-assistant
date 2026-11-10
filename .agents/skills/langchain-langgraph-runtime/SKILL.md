---
name: langchain-langgraph-runtime
description: Production-grade LangChain and LangGraph state graph architecture, persistent PostgreSQL checkpointers, human-in-the-loop interrupts, time-travel, idempotent tool execution, and Claude model integration.
license: MIT
---

# Production-Grade LangChain & LangGraph Runtime

Confirm installed LangChain/LangGraph versions and current provider model identifiers before using examples. The ecosystem changes quickly; align APIs and persistence configuration with current official docs, and do not expose private reasoning in graph traces or user-visible streams.

## Purpose & Scope
This skill outlines production engineering standards for deploying stateful, resilient multi-turn agents and graph workflows using **LangGraph** and **LangChain**, with first-class support for **Anthropic Claude** (`ChatAnthropic`), durable PostgreSQL checkpointers, and Human-in-the-Loop (HITL) approval gates.

---

## 1. Graph State Architecture & Stratification

### 1.1 Typed State Schemas
In production, graph state must be strictly typed using `TypedDict` or Pydantic models. Avoid arbitrary dictionary mutations. Use reducer annotations (e.g., `add_messages`) to ensure message history appends deterministically rather than overwriting.

```python
from typing import Annotated, Sequence, TypedDict, Literal
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentRuntimeState(TypedDict):
    # Reducer ensures append-only message progression
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # Tenant & security context (immutable across nodes)
    tenant_id: str
    customer_id: str
    auth_level: Literal["anonymous", "identified", "verified", "staff"]
    # Workflow coordination
    approval_status: Literal["none", "pending", "approved", "rejected"]
    action_payload: dict | None
    iteration_count: int
```

---

## 2. Durable Persistence & Checkpointing

### 2.1 Persistent Storage (`AsyncPostgresSaver`)
Never use in-memory checkpointers (`MemorySaver`) in production. Server restarts, autoscaling, or deployment updates will wipe active conversation states. Use PostgreSQL-backed checkpointers with dedicated connection pools.

```python
from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = "postgresql://user:password@localhost:5432/agent_runtime"

@asynccontextmanager
async def init_checkpointer():
    async with AsyncConnectionPool(
        conninfo=DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True}
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        # Idempotently runs state schema migrations on startup
        await checkpointer.setup()
        yield checkpointer
```

### 2.2 Thread Segregation
Every execution thread MUST be scoped by an explicit `thread_id` to guarantee tenant and customer isolation:
```python
run_config = {
    "configurable": {
        "thread_id": f"tenant_{tenant_id}:session_{session_id}"
    }
}
```

---

## 3. Human-in-the-Loop (HITL) & Approval Gates

### 3.1 Asynchronous Dehydration and Rehydration
Production HITL cannot block worker threads with `input()`. Instead, execution halts before sensitive nodes, state dehydrates to PostgreSQL, and the worker process frees memory immediately.

```python
from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic

# Compile graph with explicit pause gates before high-risk execution nodes
def build_agent_graph(checkpointer: AsyncPostgresSaver):
    workflow = StateGraph(AgentRuntimeState)
    
    workflow.add_node("agent_reasoning", agent_reasoning_node)
    workflow.add_node("read_tools", read_only_tool_node)
    workflow.add_node("execute_sensitive_action", sensitive_action_node)
    
    workflow.set_entry_point("agent_reasoning")
    workflow.add_conditional_edges(
        "agent_reasoning",
        route_decision,
        {"tools": "read_tools", "sensitive": "execute_sensitive_action", "end": END}
    )
    workflow.add_edge("read_tools", "agent_reasoning")
    workflow.add_edge("execute_sensitive_action", END)
    
    # HITL Gate: Pauses execution BEFORE executing sensitive actions (e.g., refunds > threshold)
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["execute_sensitive_action"]
    )
```

### 3.2 The Safe Resumption Protocol
When human staff approves or rejects an action:
1. **Never pass the original message again on resume**: Passing input data duplicates messages in the checkpointer history. Pass `None` as the input.
2. **State Modification before Resume**: Staff can inspect state via `aget_state()`, update arguments (e.g. adjust refund amount) via `aupdate_state()`, and resume.

```python
async def resume_workflow(graph, thread_id: str, staff_decision: str, modified_args: dict = None):
    config = {"configurable": {"thread_id": thread_id}}
    
    # 1. Fetch current snapshot
    snapshot = await graph.aget_state(config)
    if not snapshot.next:
        raise ValueError("Thread is not currently paused in an interrupt state.")
        
    # 2. Modify state if staff adjusted parameters
    if modified_args:
        await graph.aupdate_state(config, {"action_payload": modified_args})
        
    if staff_decision == "approved":
        await graph.aupdate_state(config, {"approval_status": "approved"})
        # 3. Resume by passing None as input
        async for event in graph.astream(None, config, stream_mode="values"):
            pass  # Process post-approval execution events
    else:
        await graph.aupdate_state(config, {"approval_status": "rejected"})
```

---

## 4. Claude Integration with LangChain (`ChatAnthropic`)

### 4.1 Native Claude Tool Binding & Prompt Caching
Configure `ChatAnthropic` using Claude 3.7 or 3.5 Sonnet with prompt caching headers and tool schemas:

```python
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

@tool
def check_order_status(order_id: str) -> dict:
    """Fetch the delivery status, carrier, and ETA for a specific order ID."""
    return {"order_id": order_id, "status": "shipped", "carrier": "Bluedart"}

def get_claude_model():
    return ChatAnthropic(
        model_name="claude-3-7-sonnet-20250219",
        temperature=0.0,
        max_tokens_to_sample=4096,
        timeout=30.0,
        max_retries=3
    ).bind_tools([check_order_status])
```

---

## 5. Idempotent Tool Execution & Deadlock Prevention

- **Idempotency Keys**: Nodes that perform external mutations must generate a deterministic idempotency key (`hash(thread_id + tool_name + args_hash)`) so duplicate resumes or network retries never double-commit actions.
- **Recursion Limits**: Always set an explicit `recursion_limit` (e.g., `config={"recursion_limit": 25}`) on `astream` to prevent infinite LLM tool-calling loops.
- **Time-Travel & State History**: Use `graph.aget_state_history(config)` to inspect prior snapshots for debugging and auditing agent decision paths.

## Primary references

- [LangChain Skills](https://github.com/langchain-ai/langchain-skills): official skills for LangChain, LangGraph, persistence, and package setup.
- [LangGraph documentation](https://docs.langchain.com/oss/python/langgraph/overview): graph construction, persistence, streaming, and human-in-the-loop behavior.
- [LangChain documentation](https://docs.langchain.com/oss/python/langchain/overview): current agents, tools, and integrations.
