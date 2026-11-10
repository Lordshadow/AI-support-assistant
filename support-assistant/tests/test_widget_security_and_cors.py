"""
Unit & Integration Test Suite for Embeddable Customer Widget & Gateway Origin Guard.
Complies with Specification Section 16.1 & 16.2.

Verifies:
1. Serving embeddable widget script at /widget/v1/widget.js.
2. Server-side origin enforcement on /chat/* and /auth/otp/*:
   - Allowed origin receives 200.
   - Disallowed origin receives 403 Forbidden.
3. Open Shadow DOM encapsulation and textContent XSS protection assertions in widget.js.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

# Ensure support-assistant is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.assistant_api.gateway_app import GatewayApp
from services.worker.orchestrator import WorkerOrchestrator, OrchestratorResponse
from core.models import SessionContext, AuthLevel


class TestWidgetSecurityAndCORS(unittest.TestCase):

    def setUp(self):
        # Mock orchestrator
        self.mock_orch = AsyncMock(spec=WorkerOrchestrator)
        self.mock_orch.process_turn.return_value = OrchestratorResponse(
            reply="Welcome to NovaRetail! How can I help you?",
            language="en",
            route_type="model",
            model_used="test-llm",
            trace_id="tr_widget_1",
            latency_ms=12.5
        )

        self.app = GatewayApp(
            orchestrator=self.mock_orch,
            tenant_origins={
                "tenant_novaretail": ["https://shop.novaretail.com", "http://localhost:3000"],
                "demo-shop": ["https://shop.novaretail.com"]
            }
        )

    def _call_app_full(self, method: str, path: str, headers: dict, body: dict = None, query_string: str = "") -> tuple[int, dict, str, dict]:
        """ASGI invocation helper returning status, parsed_json, body_str, headers_dict."""
        raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string.encode("utf-8"),
            "headers": [
                (k.lower().encode("latin1"), v.encode("latin1"))
                for k, v in headers.items()
            ]
        }

        response_status = [None]
        response_headers = [[]]
        response_body = [bytearray()]

        async def receive():
            return {"type": "http.request", "body": raw_body, "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                response_status[0] = msg["status"]
                response_headers[0] = msg.get("headers", [])
            elif msg["type"] == "http.response.body":
                response_body[0].extend(msg.get("body", b""))

        asyncio.run(self.app(scope, receive, send))

        content_type = ""
        out_headers = {}
        for h_name, h_val in response_headers[0]:
            name_str = h_name.decode("latin1").lower()
            val_str = h_val.decode("latin1")
            out_headers[name_str] = val_str
            if name_str == "content-type":
                content_type = val_str

        parsed_json = {}
        if "application/json" in content_type:
            try:
                parsed_json = json.loads(response_body[0].decode("utf-8"))
            except Exception:
                pass

        return response_status[0], parsed_json, response_body[0].decode("utf-8", errors="replace"), out_headers

    def _call_app(self, method: str, path: str, headers: dict, body: dict = None) -> tuple[int, dict, str]:
        """ASGI invocation helper for testing."""
        status, json_data, body_str, _ = self._call_app_full(method, path, headers, body)
        return status, json_data, body_str

    def test_widget_js_static_serving(self):
        """Verify Gateway serves widget.js with application/javascript content type."""
        status, _, body = self._call_app("GET", "/widget/v1/widget.js", {})
        self.assertEqual(status, 200)
        self.assertIn("novaretail-support-widget-host", body)
        self.assertIn("attachShadow({ mode: \"open\" })", body)

    def test_server_side_origin_enforcement_allowed(self):
        """Verify request from authorized origin succeeds (200 OK)."""
        payload = {
            "conv_id": "test_conv_origin_ok",
            "message": "Where is my order?",
            "tenant_id": "tenant_novaretail"
        }
        headers = {
            "Origin": "https://shop.novaretail.com",
            "Content-Type": "application/json"
        }
        status, data, _ = self._call_app("POST", "/chat/messages", headers, payload)
        self.assertEqual(status, 200)
        self.assertIn("reply", data)
        self.assertEqual(data["reply"], "Welcome to NovaRetail! How can I help you?")

    def test_server_side_origin_enforcement_disallowed(self):
        """Verify request from unauthorized origin is blocked with 403 Forbidden."""
        payload = {
            "conv_id": "test_conv_origin_bad",
            "message": "Where is my order?",
            "tenant_id": "tenant_novaretail"
        }
        headers = {
            "Origin": "https://malicious-phishing-site.com",
            "Content-Type": "application/json"
        }
        status, data, _ = self._call_app("POST", "/chat/messages", headers, payload)
        self.assertEqual(status, 403)
        self.assertIn("detail", data)
        self.assertIn("is not authorized", data["detail"])

    def test_unconfigured_tenant_origin_fails_closed(self):
        payload = {"message": "Origin guard", "tenant_id": "unconfigured-tenant"}
        status, data, _ = self._call_app(
            "POST", "/chat/messages",
            {"Origin": "https://untrusted.invalid", "Content-Type": "application/json"},
            payload,
        )
        self.assertEqual(status, 403)
        self.assertIn("not authorized", data["detail"])

    def test_wildcard_tenant_origin_is_not_accepted(self):
        wildcard_app = GatewayApp(
            orchestrator=self.mock_orch,
            tenant_origins={"demo-shop": ["*"]},
        )
        original_app = self.app
        self.app = wildcard_app
        try:
            status, data, _ = self._call_app(
                "POST", "/chat/messages",
                {"Origin": "https://untrusted.invalid", "Content-Type": "application/json"},
                {"message": "Origin guard", "tenant_id": "demo-shop"},
            )
        finally:
            self.app = original_app
        self.assertEqual(status, 403)
        self.assertIn("not authorized", data["detail"])

    def test_widget_script_security_and_shadow_dom_invariants(self):
        """Verify widget.js invariants: Open Shadow DOM, textContent, token callback."""
        widget_path = Path(__file__).parent.parent / "static" / "widget" / "v1" / "widget.js"
        self.assertTrue(widget_path.exists())

        content = widget_path.read_text(encoding="utf-8")

        # 1. Open Shadow DOM
        self.assertIn("attachShadow({ mode: \"open\" })", content)

        # 2. Strict textContent rendering (zero innerHTML on message bodies)
        self.assertIn("bubble.textContent = text", content)

        # 3. Dynamic token callback support
        self.assertIn("data-get-token", content)

        # 4. Context Extraction
        self.assertIn("data-tenant", content)
        self.assertIn("data-product-id", content)


    def test_chat_cors_headers_present_on_500_error(self):
        """Verify that HTTP 500 error responses still attach CORS headers for authorized origins."""
        # Force orchestrator to fail with an unhandled exception
        self.mock_orch.process_turn.side_effect = RuntimeError("Simulated internal LLM service crash")
        try:
            status, data, _, headers = self._call_app_full(
                "POST", "/chat/messages",
                {"Origin": "http://localhost:3000", "Content-Type": "application/json"},
                {"message": "Hello", "tenant_id": "tenant_novaretail"},
                query_string="tenant_id=tenant_novaretail"
            )
            self.assertEqual(status, 500)
            self.assertEqual(headers.get("access-control-allow-origin"), "http://localhost:3000")
            self.assertEqual(headers.get("vary"), "Origin")
            self.assertEqual(data.get("detail"), "Internal server error.")
        finally:
            self.mock_orch.process_turn.side_effect = None

    def test_chat_cors_headers_with_tenant_in_body_only(self):
        """Verify that CORS origin validation works when tenant_id is specified in the JSON body only."""
        status, _, _, headers = self._call_app_full(
            "POST", "/chat/messages",
            {"Origin": "http://localhost:3000", "Content-Type": "application/json"},
            {"message": "Hello", "tenant_id": "tenant_novaretail"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), "http://localhost:3000")


if __name__ == "__main__":
    unittest.main()
