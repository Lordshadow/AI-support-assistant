"""
Unit and Integration Tests for Support Desk Backend & Static UI Delivery
Validates Specification Section 10.3 (Staff approval for > ₹2,000 refunds), 14.2 (Why This Answer view), and Task 10.
"""

from datetime import datetime, timezone
import json
import unittest
import sys
from pathlib import Path

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import SessionContext, AuthLevel, RefundState
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter
from services.mcp_servers import (
    MCPCatalogServer, MCPOrderServer, MCPRefundServer,
    MCPHandoffServer, MCPToolDispatcher
)
from core.router.cache import CacheService
from core.router.router import AIRouter
from core.tracing.trace_collector import TraceCollector
from core.tracing.grounding_verifier import GroundingResult
from services.worker.llm_client import MockLLMClient
from services.worker.orchestrator import WorkerOrchestrator
from services.support_desk.app import SupportDeskService
from services.assistant_api.gateway_app import GatewayApp


def run_sync(coro):
    """Drive in-memory coroutine stack synchronously without OS socket dependencies."""
    stack = [coro]
    val = None
    while stack:
        try:
            nxt = stack[-1].send(val)
            val = None
            if hasattr(nxt, "send"):
                stack.append(nxt)
            else:
                val = nxt
        except StopIteration as e:
            stack.pop()
            val = e.value
    return val


def call_asgi(app: GatewayApp, method: str, path: str, headers: dict = None, body: bytes = b"", query_string: str = ""):
    """Invokes ASGI application in-memory without OS socket dependencies."""
    headers_list = []
    if headers:
        for k, v in headers.items():
            headers_list.append((k.lower().encode("latin1"), v.encode("latin1")))

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string.encode("utf-8"),
        "headers": headers_list
    }

    response_meta = {}
    response_body = bytearray()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(event):
        if event["type"] == "http.response.start":
            response_meta["status"] = event["status"]
            response_meta["headers"] = dict(event.get("headers", []))
        elif event["type"] == "http.response.body":
            response_body.extend(event.get("body", b""))

    # Execute ASGI call
    coro = app(scope, receive, send)
    run_sync(coro)

    headers_map = response_meta.get("headers", {})
    content_type = headers_map.get(b"content-type", b"").decode("latin1")
    body_text = response_body.decode("utf-8")
    parsed_json = None
    if "application/json" in content_type:
        try:
            parsed_json = json.loads(body_text)
        except Exception:
            pass

    return {
        "status": response_meta.get("status", 500),
        "content_type": content_type,
        "text": body_text,
        "json": parsed_json
    }


class TestSupportDeskBackend(unittest.TestCase):
    def setUp(self):
        self.orders = MockOrderAdapter()
        self.refunds = MockRefundAdapter(self.orders, auto_limit_inr=2000)
        self.catalog = MockCatalogAdapter()
        self.dispatcher = MCPToolDispatcher(
            catalog_server=MCPCatalogServer(self.catalog),
            order_server=MCPOrderServer(self.orders),
            refund_server=MCPRefundServer(self.refunds),
            handoff_server=MCPHandoffServer()
        )
        self.cache = CacheService()
        self.router = AIRouter(cache_service=self.cache, dispatcher=self.dispatcher)
        self.collector = TraceCollector()
        self.orchestrator = WorkerOrchestrator(
            router=self.router,
            dispatcher=self.dispatcher,
            llm_client=MockLLMClient()
        )
        self.desk_service = SupportDeskService(
            refund_adapter=self.refunds,
            trace_collector=self.collector
        )
        self.gateway = GatewayApp(
            orchestrator=self.orchestrator,
            support_desk_service=self.desk_service
        )

        # Seed two refunds: 1 auto-approved (<= 2000) and 1 pending supervisor review (> 2000)
        # 1. ORD-5501 (₹1,499 -> auto-approved)
        run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-5501",
            amount_inr=1499,
            reason="Earbuds defective",
            idempotency_key="idemp_auto_001"
        ))

        # 2. ORD-8812 (₹4,500 -> pending supervisor review)
        self.pending_refund = run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-8812",
            amount_inr=4500,
            reason="Smartwatch display cracked on arrival",
            idempotency_key="idemp_pending_002"
        ))

    def test_get_pending_refunds_filters_by_threshold(self):
        """Only refunds > ₹2,000 appear in the pending supervisor queue."""
        pending = run_sync(self.desk_service.get_pending_refunds())
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["refund_id"], self.pending_refund.refund_id)
        self.assertEqual(pending[0]["amount_inr"], 4500)
        self.assertEqual(pending[0]["state"], "pending_approval")

    def test_supervisor_approve_refund(self):
        """Supervisor approves a pending refund with audit notes."""
        ref_id = self.pending_refund.refund_id
        ok, msg, res = run_sync(self.desk_service.approve_refund(
            refund_id=ref_id,
            staff_id="STAFF-882",
            notes="Customer provided courier damage confirmation."
        ))

        self.assertTrue(ok)
        self.assertEqual(res["state"], "approved")
        self.assertEqual(res["decided_by"], "STAFF-882")
        self.assertIn("courier damage", res["note"])

        # Pending queue should now be empty
        pending = run_sync(self.desk_service.get_pending_refunds())
        self.assertEqual(len(pending), 0)

    def test_supervisor_reject_refund_requires_mandatory_notes(self):
        """Rejection without an audit note is blocked; with note succeeds."""
        ref_id = self.pending_refund.refund_id

        # Missing note rejected
        ok, msg, res = run_sync(self.desk_service.reject_refund(
            refund_id=ref_id,
            staff_id="STAFF-882",
            notes=""
        ))
        self.assertFalse(ok)
        self.assertIn("mandatory", msg)

        # Valid note accepted
        ok_valid, msg_valid, res_valid = run_sync(self.desk_service.reject_refund(
            refund_id=ref_id,
            staff_id="STAFF-882",
            notes="Physical damage not covered by warranty per Store Policy 2.4."
        ))
        self.assertTrue(ok_valid)
        self.assertEqual(res_valid["state"], "rejected")

    def test_why_this_answer_trace_inspection(self):
        """Generates Section 14.2 Explainability View for Support Desk staff."""
        trace = self.collector.record_turn(
            conv_id="c_desk_view",
            customer_message="I want to return ORD-8812, phone 9876543210",
            detected_language="en",
            route_type="large_model",
            intent="refund_request",
            auth_level="verified",
            final_reply="Your refund of ₹4,500 has been submitted to a supervisor for review.",
            resolved_product_id="P8812",
            tool_calls=[{"name": "create_refund_request", "args": {"order_id": "ORD-8812"}}],
            model_used="llama-3.3-70b-versatile",
            latency_ms=180.2,
            grounding_result=GroundingResult(passed=True),
            refund_decision={"order_id": "ORD-8812", "state": "pending_approval", "amount_inr": 4500}
        )

        why_view = self.desk_service.get_why_this_answer_trace(trace.trace_id)
        self.assertIsNotNone(why_view)
        self.assertEqual(why_view["routing_explanation"]["inferred_intent"], "refund_request")
        self.assertEqual(why_view["factual_grounding"]["passed_gate"], True)
        self.assertEqual(why_view["audit_trail"]["auth_level"], "verified")
        # DPDP Masking confirmed in staff view
        self.assertNotIn("9876543210", why_view["audit_trail"]["sanitized_user_input"])

    def test_support_desk_api_endpoints_via_gateway(self):
        """Tests /desk REST endpoints delivered through ASGI gateway."""
        # 1. GET /desk/refunds/pending
        res_list = call_asgi(self.gateway, "GET", "/desk/refunds/pending")
        self.assertEqual(res_list["status"], 200)
        self.assertEqual(len(res_list["json"]), 1)
        self.assertEqual(res_list["json"][0]["order_id"], "ORD-8812")

        # 2. POST /desk/refunds/{id}/approve
        ref_id = self.pending_refund.refund_id
        res_app = call_asgi(
            self.gateway,
            "POST",
            f"/desk/refunds/{ref_id}/approve",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"staff_id": "STAFF-882", "notes": "Approved by supervisor"}).encode("utf-8")
        )
        self.assertEqual(res_app["status"], 200)
        self.assertTrue(res_app["json"]["success"])
        self.assertEqual(res_app["json"]["refund"]["state"], "approved")

        # 3. GET /desk/stats
        res_stats = call_asgi(self.gateway, "GET", "/desk/stats")
        self.assertEqual(res_stats["status"], 200)
        self.assertEqual(res_stats["json"]["supervisor_approved"], 1)

    def test_static_ui_widget_and_desk_delivery(self):
        """Tests that customer chat widget and supervisor dashboard HTML files are served."""
        # 1. Customer Chat Widget
        res_widget = call_asgi(self.gateway, "GET", "/widget")
        self.assertEqual(res_widget["status"], 200)
        self.assertIn("text/html", res_widget["content_type"])
        self.assertIn("NovaRetail Customer Support Assistant", res_widget["text"])
        self.assertIn("English • தமிழ் • Tanglish", res_widget["text"])

        # 2. Supervisor Support Desk
        res_desk = call_asgi(self.gateway, "GET", "/desk")
        self.assertEqual(res_desk["status"], 200)
        self.assertIn("text/html", res_desk["content_type"])
        self.assertIn("NovaRetail Support Desk", res_desk["text"])
        self.assertIn("Supervisor Console", res_desk["text"])


if __name__ == "__main__":
    unittest.main()
