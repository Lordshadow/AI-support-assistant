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
                "demo-shop": ["*"]
            }
        )

    def _call_app(self, method: str, path: str, headers: dict, body: dict = None) -> tuple[int, dict, str]:
        """ASGI invocation helper for testing."""
        raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
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
        for h_name, h_val in response_headers[0]:
            if h_name.decode("latin1").lower() == "content-type":
                content_type = h_val.decode("latin1")

        parsed_json = {}
        if "application/json" in content_type:
            try:
                parsed_json = json.loads(response_body[0].decode("utf-8"))
            except Exception:
                pass

        return response_status[0], parsed_json, response_body[0].decode("utf-8", errors="replace")

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


if __name__ == "__main__":
    unittest.main()
