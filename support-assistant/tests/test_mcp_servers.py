"""
Unit and Integration Tests for MCP Tool Servers and Dispatcher
Validates Specification Section 7, 7.6, 10, 15.1, and 'Where MCP fits'.
"""

import unittest
import sys
from pathlib import Path

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import SessionContext, AuthLevel, PageContext
from core.mcp_tool_definitions import MCP_TOOL_SCHEMAS
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter
from services.mcp_servers import (
    mint_internal_token, ctx_from_token,
    MCPCatalogServer, MCPOrderServer, MCPRefundServer,
    MCPHandoffServer, MCPToolDispatcher
)


def run_sync(coro):
    """Drive in-memory coroutine without socket dependencies."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value


class TestMCPServers(unittest.TestCase):

    def setUp(self):
        self.catalog_adapter = MockCatalogAdapter()
        self.order_adapter = MockOrderAdapter()
        self.refund_adapter = MockRefundAdapter(self.order_adapter, auto_limit_inr=2000)

        self.catalog_server = MCPCatalogServer(self.catalog_adapter)
        self.order_server = MCPOrderServer(self.order_adapter)
        self.refund_server = MCPRefundServer(self.refund_adapter)
        self.handoff_server = MCPHandoffServer()

        self.dispatcher = MCPToolDispatcher(
            catalog_server=self.catalog_server,
            order_server=self.order_server,
            refund_server=self.refund_server,
            handoff_server=self.handoff_server
        )

        self.anon_ctx = SessionContext(tenant_id="demo", conv_id="c1", level=AuthLevel.ANONYMOUS)
        self.ident_ctx = SessionContext(tenant_id="demo", conv_id="c2", customer_id="CUST-42", level=AuthLevel.IDENTIFIED)
        self.verif_ctx = SessionContext(tenant_id="demo", conv_id="c3", customer_id="CUST-42", level=AuthLevel.VERIFIED)

    def test_mcp_tool_schemas_hide_identity(self):
        """Rule 1: Identity is not a model parameter. Tool schema must NEVER contain customer_id."""
        forbidden_params = {"customer_id", "auth_token", "level", "tenant_id", "jwt"}
        for tool in MCP_TOOL_SCHEMAS:
            props = tool["function"]["parameters"].get("properties", {})
            for forbidden in forbidden_params:
                self.assertNotIn(
                    forbidden,
                    props,
                    f"Security violation: tool '{tool['function']['name']}' exposes '{forbidden}' to LLM!"
                )

    def test_internal_token_mint_and_decode(self):
        token = mint_internal_token(self.verif_ctx)
        self.assertIsInstance(token, str)
        decoded_ctx = ctx_from_token(token)

        self.assertEqual(decoded_ctx.customer_id, "CUST-42")
        self.assertEqual(decoded_ctx.level, AuthLevel.VERIFIED)
        self.assertEqual(decoded_ctx.tenant_id, "demo")

        storefront_ctx = SessionContext(
            tenant_id="ApexStore", conv_id="c-store", customer_id="7",
            level=AuthLevel.IDENTIFIED, storefront_customer_token="signed-storefront-token",
            storefront_refund_verification_token="storefront-order-otp-token"
        )
        decoded_storefront_ctx = ctx_from_token(mint_internal_token(storefront_ctx))
        self.assertEqual(decoded_storefront_ctx.storefront_customer_token, "signed-storefront-token")
        self.assertEqual(decoded_storefront_ctx.storefront_refund_verification_token, "storefront-order-otp-token")

    def test_order_server_forwards_storefront_token_to_owned_order_lookup(self):
        class TokenAwareOrderAdapter:
            received_token = None
            async def get_order(self, customer_id, order_id, customer_token=None):
                self.received_token = customer_token
                return await self.base.get_order(customer_id, order_id)
            async def list_recent_orders(self, customer_id, limit=5, customer_token=None):
                return await self.base.list_recent_orders(customer_id, limit=limit)
            async def get_tracking(self, customer_id, order_id, customer_token=None):
                return await self.base.get_tracking(customer_id, order_id)

        adapter = TokenAwareOrderAdapter()
        adapter.base = self.order_adapter
        server = MCPOrderServer(adapter)
        dispatcher = MCPToolDispatcher(self.catalog_server, server, self.refund_server, self.handoff_server)
        ctx = SessionContext(
            tenant_id="ApexStore", conv_id="c-store-order", customer_id="CUST-42",
            level=AuthLevel.IDENTIFIED, storefront_customer_token="signed-storefront-token"
        )
        result = run_sync(dispatcher.execute_tool("get_order_status", {"order_id": "ORD-1029"}, ctx))

        self.assertTrue(result.get("found"))
        self.assertEqual(adapter.received_token, "signed-storefront-token")

    def test_refund_server_forwards_storefront_token_through_auto_refund(self):
        class TokenAwareRefundAdapter:
            def __init__(self, base):
                self.base = base
                self.tokens = []
                self.verification_tokens = []
            async def check_eligibility(self, customer_id, order_id, item_id=None, customer_token=None):
                self.tokens.append(customer_token)
                return await self.base.check_eligibility(customer_id, order_id, item_id=item_id)
            async def request_refund(self, customer_id, order_id, amount_inr, reason, idempotency_key, customer_token=None, storefront_verification_token=None):
                self.tokens.append(customer_token)
                self.verification_tokens.append(storefront_verification_token)
                return await self.base.request_refund(customer_id, order_id, amount_inr, reason, idempotency_key)

        adapter = TokenAwareRefundAdapter(self.refund_adapter)
        server = MCPRefundServer(adapter)
        dispatcher = MCPToolDispatcher(self.catalog_server, self.order_server, server, self.handoff_server)
        ctx = SessionContext(
            tenant_id="ApexStore", conv_id="c-store-refund", customer_id="CUST-42",
            level=AuthLevel.VERIFIED, storefront_customer_token="signed-storefront-token",
            storefront_refund_verification_token="storefront-order-otp-token"
        )

        eligibility = run_sync(dispatcher.execute_tool(
            "check_refund_eligibility", {"order_id": "ORD-5501"}, ctx
        ))
        result = run_sync(dispatcher.execute_tool(
            "create_refund_request", {"order_id": "ORD-5501", "reason": "Product return requested"}, ctx
        ))

        self.assertTrue(eligibility["is_eligible"])
        self.assertEqual(result["state"], "processed")
        self.assertEqual(adapter.tokens, ["signed-storefront-token"] * 3)
        self.assertEqual(adapter.verification_tokens, ["storefront-order-otp-token"])

    def test_storefront_refund_requires_storefront_otp_token(self):
        ctx = SessionContext(
            tenant_id="ApexStore", conv_id="c-store-no-otp", customer_id="CUST-42",
            level=AuthLevel.VERIFIED, storefront_customer_token="signed-storefront-token"
        )
        result = run_sync(self.dispatcher.execute_tool(
            "create_refund_request",
            {"order_id": "ORD-5501", "reason": "Product return requested"},
            ctx,
        ))
        self.assertEqual(result.get("needs_auth"), "otp_required")

    def test_order_server_requires_identified_level(self):
        # Anonymous request blocked
        res_anon = run_sync(self.dispatcher.execute_tool(
            "get_order_status", {"order_id": "ORD-1029"}, self.anon_ctx
        ))
        self.assertFalse(res_anon.get("authorized", True))
        self.assertEqual(res_anon.get("needs_auth"), "login_required")

        # Identified request succeeds
        res_ident = run_sync(self.dispatcher.execute_tool(
            "get_order_status", {"order_id": "ORD-1029"}, self.ident_ctx
        ))
        self.assertTrue(res_ident.get("found"))
        self.assertEqual(res_ident["order_id"], "ORD-1029")

    def test_order_server_enforces_ownership(self):
        # CUST-42 queries ORD-9999 (owned by CUST-99)
        res = run_sync(self.dispatcher.execute_tool(
            "get_order_status", {"order_id": "ORD-9999"}, self.ident_ctx
        ))
        self.assertFalse(res.get("found"))
        self.assertIn("not found for your account", res["message"])

    def test_refund_server_requires_verified_otp_level(self):
        # Identified session without OTP blocked
        res_ident = run_sync(self.dispatcher.execute_tool(
            "create_refund_request", {"order_id": "ORD-5501", "reason": "damaged"}, self.ident_ctx
        ))
        self.assertFalse(res_ident.get("authorized", True))
        self.assertEqual(res_ident.get("needs_auth"), "otp_required")
        self.assertIn("email address", res_ident.get("message", "").lower())
        self.assertNotIn("mobile", res_ident.get("message", "").lower())

        # Verified session with OTP succeeds
        res_verif = run_sync(self.dispatcher.execute_tool(
            "create_refund_request", {"order_id": "ORD-5501", "reason": "damaged"}, self.verif_ctx
        ))
        self.assertEqual(res_verif.get("state"), "processed")
        self.assertTrue(res_verif["refund_id"].startswith("REF-"))

    def test_refund_auto_limit_under_2000_vs_over_2000(self):
        # Under ₹2,000 -> processed
        res_small = run_sync(self.dispatcher.execute_tool(
            "create_refund_request", {"order_id": "ORD-5501", "reason": "earbuds defective"}, self.verif_ctx
        ))
        self.assertEqual(res_small["state"], "processed")

        # Over ₹2,000 -> pending_approval
        res_large = run_sync(self.dispatcher.execute_tool(
            "create_refund_request", {"order_id": "ORD-8812", "reason": "watch screen dead"}, self.verif_ctx
        ))
        self.assertEqual(res_large["state"], "pending_approval")
        self.assertIn("exceeds the instant auto-refund limit", res_large["message"])

    def test_catalog_server_find_product_and_price(self):
        res_find = run_sync(self.dispatcher.execute_tool(
            "find_product", {"name_text": "Pulse Buds 141"}, self.anon_ctx
        ))
        self.assertTrue(res_find["found"])
        self.assertEqual(res_find["candidates"][0]["product_id"], "P1041")

        res_price = run_sync(self.dispatcher.execute_tool(
            "get_product_price", {"product_id": "P1041"}, self.anon_ctx
        ))
        self.assertEqual(res_price["price"], 1499)
        self.assertEqual(res_price["discount_price"], 1299)

    def test_handoff_server_creates_ticket(self):
        res = run_sync(self.dispatcher.execute_tool(
            "handoff_to_human", {"reason": "agitated customer", "summary": "Customer demands immediate compensation"}, self.anon_ctx
        ))
        self.assertTrue(res["success"])
        self.assertTrue(res["ticket_id"].startswith("ESC-"))

    def test_handoff_server_persists_escalation_when_configured(self):
        persisted = []

        async def persist(*args):
            persisted.append(args)

        server = MCPHandoffServer(persist_escalation=persist)
        dispatcher = MCPToolDispatcher(
            catalog_server=self.catalog_server,
            order_server=self.order_server,
            refund_server=self.refund_server,
            handoff_server=server,
        )
        res = run_sync(dispatcher.execute_tool(
            "handoff_to_human",
            {"reason": "customer request", "summary": "Needs an executive"},
            self.verif_ctx,
        ))

        self.assertTrue(res["success"])
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0][0], self.verif_ctx.conv_id)
        self.assertEqual(persisted[0][5], self.verif_ctx.customer_id)
        self.assertEqual(persisted[0][6], self.verif_ctx.channel)

    def test_dispatcher_records_explainability_traces(self):
        initial_trace_count = len(self.dispatcher.traces)
        run_sync(self.dispatcher.execute_tool(
            "get_product_price", {"product_id": "P1041"}, self.anon_ctx
        ))
        self.assertEqual(len(self.dispatcher.traces), initial_trace_count + 1)
        last_trace = self.dispatcher.traces[-1]
        self.assertEqual(last_trace["tool_name"], "get_product_price")
        self.assertEqual(last_trace["auth_level"], "anonymous")
        self.assertIn("latency_ms", last_trace)

    def test_page_context_mismatch_is_rejected(self):
        ctx = SessionContext(
            tenant_id="demo",
            conv_id="context-mismatch",
            level=AuthLevel.ANONYMOUS,
            page_context=PageContext(
                url="https://shop.example/products/P1041",
                page_type="product_details",
                product_id="P1041",
            ),
        )
        res = run_sync(self.dispatcher.execute_tool(
            "get_product_details", {"product_id": "P1031"}, ctx
        ))
        self.assertEqual(res["error"], "CONTEXT_MISMATCH")


if __name__ == "__main__":
    unittest.main()
