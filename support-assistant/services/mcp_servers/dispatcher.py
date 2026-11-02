"""
MCP Tool Dispatcher (The Orchestrator's MCP Client)
Complies with Specification Section 7, 7.6, and 'Where MCP fits'.

Binds the AI worker to the four MCP servers (Catalog, Orders, Refunds, Handoff).
Injects short-lived transport tokens for identity verification.
Records execution traces for R5 Explainability.
"""

from typing import Any, Optional
import time

from core.models import SessionContext
from core.mcp_tool_definitions import MCP_TOOL_SCHEMAS
from services.mcp_servers.auth import mint_internal_token
from services.mcp_servers.catalog_server import MCPCatalogServer
from services.mcp_servers.order_server import MCPOrderServer
from services.mcp_servers.refund_server import MCPRefundServer
from services.mcp_servers.handoff_server import MCPHandoffServer


class MCPToolDispatcher:
    """Unified client and router for MCP tool execution."""

    def __init__(
        self,
        catalog_server: MCPCatalogServer,
        order_server: MCPOrderServer,
        refund_server: MCPRefundServer,
        handoff_server: Optional[MCPHandoffServer] = None
    ):
        self.catalog = catalog_server
        self.orders = order_server
        self.refunds = refund_server
        self.handoff = handoff_server or MCPHandoffServer()
        self.traces: list[dict[str, Any]] = []

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Returns the OpenAI/Groq function schemas."""
        return MCP_TOOL_SCHEMAS

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: SessionContext
    ) -> dict[str, Any]:
        """
        Executes a tool call.
        Automatically injects transport token for identity isolation.
        Logs trace for explainability.
        """
        start_time = time.perf_counter()
        token = mint_internal_token(ctx)

        # 1. Route to Catalog Server
        if tool_name == "find_product":
            result = await self.catalog.find_product(args.get("name_text", ""))
        elif tool_name == "get_product_price":
            result = await self.catalog.get_product_price(args.get("product_id", ""))
        elif tool_name == "get_product_details":
            result = await self.catalog.get_product_details(args.get("product_id", ""))
        elif tool_name == "search_product_docs":
            result = await self.catalog.search_product_docs(
                args.get("product_id", ""), args.get("question", "")
            )
        elif tool_name == "search_policy":
            result = await self.catalog.search_policy(args.get("question", ""))

        # 2. Route to Order Server (Requires Auth Token)
        elif tool_name == "get_order_status":
            result = await self.orders.get_order_status(args.get("order_id", ""), auth_token=token)
        elif tool_name == "list_recent_orders":
            result = await self.orders.list_recent_orders(auth_token=token)
        elif tool_name == "get_tracking":
            result = await self.orders.get_tracking(args.get("order_id", ""), auth_token=token)

        # 3. Route to Refund Server (Requires Auth Token + Step-up OTP)
        elif tool_name == "check_refund_eligibility":
            result = await self.refunds.check_refund_eligibility(
                order_id=args.get("order_id", ""),
                auth_token=token,
                item_id=args.get("item_id")
            )
        elif tool_name == "create_refund_request":
            result = await self.refunds.create_refund_request(
                order_id=args.get("order_id", ""),
                reason=args.get("reason", "Customer requested refund"),
                auth_token=token,
                amount_inr=args.get("amount_inr")
            )
        elif tool_name == "get_refund_status":
            result = await self.refunds.get_refund_status(
                refund_id=args.get("refund_id", ""),
                auth_token=token
            )

        # 4. Route to Escalation Handoff
        elif tool_name == "handoff_to_human":
            result = await self.handoff.handoff_to_human(
                reason=args.get("reason", "General escalation"),
                summary=args.get("summary", ""),
                conv_id=ctx.conv_id
            )
        else:
            result = {"error": f"Unknown tool: '{tool_name}'"}

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Record Execution Trace for R5 Explainability
        trace_record = {
            "conv_id": ctx.conv_id,
            "tool_name": tool_name,
            "args": args,
            "result_status": "success" if "error" not in result else "failed",
            "latency_ms": latency_ms,
            "auth_level": ctx.level.value
        }
        self.traces.append(trace_record)

        return result
