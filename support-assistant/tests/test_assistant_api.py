"""
Unit and Integration Tests for Assistant API Gateway, Channel Security, and Auth
Validates Specification Section 15.1 (Auth Hierarchy), 15.1.1 (WhatsApp), 15.1.2 (Web JWT), and 15.1.3 (OTP).
"""

import unittest
import sys
from pathlib import Path
import json
import hmac
import hashlib

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import SessionContext, AuthLevel
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter
from services.mcp_servers import (
    MCPCatalogServer, MCPOrderServer, MCPRefundServer,
    MCPHandoffServer, MCPToolDispatcher
)
from core.router.cache import CacheService
from core.router.router import AIRouter
from services.worker.llm_client import MockLLMClient
from services.worker.orchestrator import WorkerOrchestrator
from services.assistant_api.jwt_auth import mint_customer_token, verify_customer_token
from services.assistant_api.otp_service import OTPService
from services.assistant_api.whatsapp_security import WhatsAppSecurity
from services.assistant_api.gateway_app import GatewayApp


def run_sync(coro):
    """Drive in-memory coroutine stack without socket dependencies."""
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
        "text": body_text,
        "json": parsed_json
    }


class TestAssistantAPIGateway(unittest.TestCase):
    def setUp(self):
        # 1. MockShop Adapters
        self.catalog_adapter = MockCatalogAdapter()
        self.order_adapter = MockOrderAdapter()
        self.refund_adapter = MockRefundAdapter(self.order_adapter, auto_limit_inr=2000)

        # 2. FastMCP Tool Servers
        self.cat_server = MCPCatalogServer(self.catalog_adapter)
        self.ord_server = MCPOrderServer(self.order_adapter)
        self.ref_server = MCPRefundServer(self.refund_adapter)
        self.hnd_server = MCPHandoffServer()

        self.dispatcher = MCPToolDispatcher(
            catalog_server=self.cat_server,
            order_server=self.ord_server,
            refund_server=self.ref_server,
            handoff_server=self.hnd_server
        )

        # 3. Router & Orchestrator
        self.cache = CacheService()
        self.router = AIRouter(cache_service=self.cache, dispatcher=self.dispatcher)
        self.mock_llm = MockLLMClient()
        self.orchestrator = WorkerOrchestrator(
            router=self.router,
            dispatcher=self.dispatcher,
            llm_client=self.mock_llm
        )

        # 4. Security & Gateway
        self.app_secret = "test_whatsapp_secret_9941"
        self.verify_token = "novaretail_verify_token_secure"
        self.wa_sec = WhatsAppSecurity(app_secret=self.app_secret, verify_token=self.verify_token)
        self.otp_service = OTPService()

        self.gateway = GatewayApp(
            orchestrator=self.orchestrator,
            otp_service=self.otp_service,
            whatsapp_security=self.wa_sec
        )

    # ========================================================================
    # 1. Customer JWT Verification (Section 15.1.2)
    # ========================================================================

    def test_customer_jwt_mint_and_verify(self):
        token = mint_customer_token(customer_id="cust_9921", tenant_id="demo-shop")
        auth_header = f"Bearer {token}"

        session = verify_customer_token(auth_header, expected_tenant="demo-shop", conv_id="conv_1")
        self.assertEqual(session.customer_id, "cust_9921")
        self.assertEqual(session.level, AuthLevel.IDENTIFIED)
        self.assertEqual(session.channel, "web")

    def test_customer_jwt_tenant_mismatch_downgrades(self):
        token = mint_customer_token(customer_id="cust_9921", tenant_id="different-shop")
        auth_header = f"Bearer {token}"

        # Tenant mismatch should gracefully drop to anonymous
        session = verify_customer_token(auth_header, expected_tenant="demo-shop", conv_id="conv_2")
        self.assertIsNone(session.customer_id)
        self.assertEqual(session.level, AuthLevel.ANONYMOUS)

    def test_customer_jwt_invalid_or_missing_header(self):
        session_none = verify_customer_token(None, expected_tenant="demo-shop")
        self.assertEqual(session_none.level, AuthLevel.ANONYMOUS)

        session_bad = verify_customer_token("Bearer invalid.tampered.token", expected_tenant="demo-shop")
        self.assertEqual(session_bad.level, AuthLevel.ANONYMOUS)

    # ========================================================================
    # 2. OTP Step-Up Lifecycle (Section 15.1.3)
    # ========================================================================

    def test_otp_challenge_and_verification(self):
        session = SessionContext(
            tenant_id="demo-shop",
            conv_id="conv_otp_test",
            customer_id="cust_101",
            level=AuthLevel.IDENTIFIED,
            channel="web"
        )

        # 1. Create challenge with known code
        ch_id, code = self.otp_service.create_challenge(
            session=session,
            destination="+919876543210",
            fixed_code_for_test="123456"
        )
        self.assertTrue(ch_id.startswith("otp_"))
        self.assertEqual(code, "123456")

        # 2. Failed attempt (wrong code)
        success, msg, s_fail = self.otp_service.verify_otp(ch_id, "000000", session)
        self.assertFalse(success)
        self.assertIn("2 attempt(s) remaining", msg)
        self.assertEqual(s_fail.level, AuthLevel.IDENTIFIED)

        # 3. Successful verification
        success, msg, s_verified = self.otp_service.verify_otp(ch_id, "123456", session)
        self.assertTrue(success)
        self.assertEqual(s_verified.level, AuthLevel.VERIFIED)
        self.assertIsNotNone(s_verified.verified_until)

        # 4. Challenge cannot be reused once verified
        success2, msg2, _ = self.otp_service.verify_otp(ch_id, "123456", session)
        self.assertFalse(success2)
        self.assertIn("already been verified", msg2)

    def test_otp_lockout_after_three_attempts(self):
        session = SessionContext(tenant_id="demo-shop", conv_id="conv_lockout")
        ch_id, _ = self.otp_service.create_challenge(session, "+919876543210", fixed_code_for_test="889900")

        self.otp_service.verify_otp(ch_id, "111111", session)  # attempt 1
        self.otp_service.verify_otp(ch_id, "222222", session)  # attempt 2
        success, msg, _ = self.otp_service.verify_otp(ch_id, "333333", session)  # attempt 3

        self.assertFalse(success)
        self.assertIn("Maximum attempts exceeded", msg)

        # Further attempts fail with lockout message
        success, msg_lock, _ = self.otp_service.verify_otp(ch_id, "889900", session)
        self.assertFalse(success)
        self.assertIn("invalidated", msg_lock)

    # ========================================================================
    # 3. WhatsApp Security & Deduplication (Section 15.1.1)
    # ========================================================================

    def test_whatsapp_webhook_handshake(self):
        # Valid handshake
        valid_res = call_asgi(
            self.gateway,
            "GET",
            "/webhooks/whatsapp",
            query_string=f"hub.mode=subscribe&hub.challenge=987654321&hub.verify_token={self.verify_token}"
        )
        self.assertEqual(valid_res["status"], 200)
        self.assertEqual(valid_res["text"], "987654321")

        # Invalid token
        invalid_res = call_asgi(
            self.gateway,
            "GET",
            "/webhooks/whatsapp",
            query_string="hub.mode=subscribe&hub.challenge=987654321&hub.verify_token=wrong_token"
        )
        self.assertEqual(invalid_res["status"], 403)

    def test_whatsapp_signature_verification_and_deduplication(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "id": "wamid.HBgLMTIzNDU2",
                            "from": "919876543210",
                            "text": {"body": "வணக்கம்"}
                        }]
                    }
                }]
            }]
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_sig = "sha256=" + hmac.new(self.app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

        # 1. Invalid signature rejected with 401
        res_bad_sig = call_asgi(
            self.gateway,
            "POST",
            "/webhooks/whatsapp",
            headers={"X-Hub-Signature-256": "sha256=wrongsignature"},
            body=body_bytes
        )
        self.assertEqual(res_bad_sig["status"], 401)

        # 2. Valid signature accepted and processed (fast ACK)
        res_good = call_asgi(
            self.gateway,
            "POST",
            "/webhooks/whatsapp",
            headers={"X-Hub-Signature-256": valid_sig},
            body=body_bytes
        )
        self.assertEqual(res_good["status"], 200)
        self.assertEqual(res_good["json"]["status"], "delivered")
        self.assertEqual(res_good["json"]["sender"], "919876543210")
        self.assertEqual(res_good["json"]["language"], "ta")

        # 3. Network retry with same wamid is deduplicated without re-execution
        res_dup = call_asgi(
            self.gateway,
            "POST",
            "/webhooks/whatsapp",
            headers={"X-Hub-Signature-256": valid_sig},
            body=body_bytes
        )
        self.assertEqual(res_dup["status"], 200)
        self.assertEqual(res_dup["json"]["status"], "duplicate_ignored")
        self.assertEqual(res_dup["json"]["message_id"], "wamid.HBgLMTIzNDU2")

    # ========================================================================
    # 4. Gateway Chat Message & Step-Up Pipeline
    # ========================================================================

    def test_gateway_chat_anonymous_to_identified(self):
        # 1. Anonymous greeting
        res_anon = call_asgi(
            self.gateway,
            "POST",
            "/chat/messages",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"message": "Hello"}).encode("utf-8")
        )
        self.assertEqual(res_anon["status"], 200)
        self.assertEqual(res_anon["json"]["auth_level"], "anonymous")
        self.assertIn("NovaRetail", res_anon["json"]["reply"])

        # 2. Identified message with customer JWT
        token = mint_customer_token("cust_101")
        conv_id = res_anon["json"]["conv_id"]
        res_ident = call_asgi(
            self.gateway,
            "POST",
            "/chat/messages",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            },
            body=json.dumps({"conv_id": conv_id, "message": "My order ORD-1001"}).encode("utf-8")
        )
        self.assertEqual(res_ident["status"], 200)
        self.assertEqual(res_ident["json"]["auth_level"], "identified")
        self.assertTrue(len(res_ident["json"]["reply"]) > 0)

    def test_gateway_otp_step_up_flow(self):
        conv_id = "conv_stepup_1"

        # 1. Send OTP
        res_send = call_asgi(
            self.gateway,
            "POST",
            "/auth/otp/send",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"conv_id": conv_id, "destination": "+919876543210"}).encode("utf-8")
        )
        self.assertEqual(res_send["status"], 200)
        ch_id = res_send["json"]["challenge_id"]

        # Retrieve test record code for verification
        record = self.otp_service._challenges[ch_id]
        # Calculate matching code from the record salt
        # Instead, verify using the known internal challenge
        test_code = "654321"
        ch_id2, _ = self.otp_service.create_challenge(
            session=self.gateway.get_or_create_session("demo-shop", conv_id),
            destination="+919876543210",
            fixed_code_for_test=test_code
        )

        # 2. Verify OTP
        res_verify = call_asgi(
            self.gateway,
            "POST",
            "/auth/otp/verify",
            headers={"Content-Type": "application/json"},
            body=json.dumps({
                "conv_id": conv_id,
                "challenge_id": ch_id2,
                "candidate_code": test_code
            }).encode("utf-8")
        )
        self.assertEqual(res_verify["status"], 200)
        self.assertTrue(res_verify["json"]["success"])
        self.assertEqual(res_verify["json"]["auth_level"], "verified")

        # 3. Subsequent chat message preserves VERIFIED status
        res_chat = call_asgi(
            self.gateway,
            "POST",
            "/chat/messages",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"conv_id": conv_id, "message": "Can I cancel ORD-1001?"}).encode("utf-8")
        )
        self.assertEqual(res_chat["status"], 200)
        self.assertEqual(res_chat["json"]["auth_level"], "verified")

    def test_gateway_health(self):
        res = call_asgi(self.gateway, "GET", "/health")
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["json"]["status"], "healthy")
        self.assertEqual(res["json"]["service"], "novaretail-assistant-api")


if __name__ == "__main__":
    unittest.main()
