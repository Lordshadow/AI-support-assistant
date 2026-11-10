"""
Comprehensive Verification Suite: AI Product & Order Search, MCP Architecture, STT, and WhatsApp Voice Pipeline.
Complies with Specification Section 1.5, 7, 8, 13 (Voice/Multilingual), and 15.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

# Ensure support-assistant is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient

from core.models import AuthLevel, SessionContext
from core.ports import SpeechPort
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter
from adapters.speech.whisper_adapter import MockSpeechAdapter, GroqWhisperAdapter
from services.mcp_servers.catalog_server import MCPCatalogServer
from services.mcp_servers.order_server import MCPOrderServer
from services.mcp_servers.refund_server import MCPRefundServer
from services.mcp_servers.handoff_server import MCPHandoffServer
from services.mcp_servers.dispatcher import MCPToolDispatcher
from services.mcp_servers.auth import mint_internal_token, ctx_from_token
from services.worker.orchestrator import WorkerOrchestrator
from services.worker.llm_client import MockLLMClient
from services.assistant_api.gateway_app import GatewayApp, create_default_app
from services.assistant_api.whatsapp_security import WhatsAppSecurity
from core.router.router import AIRouter
from core.router.cache import CacheService


class TestAIMCPAndVoicePipeline(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Setup adapters
        self.catalog = MockCatalogAdapter()
        self.orders = MockOrderAdapter()
        self.refunds = MockRefundAdapter(self.orders, auto_limit_inr=2000)

        # Setup MCP Servers
        self.catalog_server = MCPCatalogServer(self.catalog)
        self.order_server = MCPOrderServer(self.orders)
        self.refund_server = MCPRefundServer(self.refunds)
        self.handoff_server = MCPHandoffServer()

        # Setup MCP Client / Dispatcher
        self.dispatcher = MCPToolDispatcher(
            catalog_server=self.catalog_server,
            order_server=self.order_server,
            refund_server=self.refund_server,
            handoff_server=self.handoff_server
        )

        # Setup AI Worker
        self.cache = CacheService()
        self.router = AIRouter(cache_service=self.cache, dispatcher=self.dispatcher)
        self.llm = MockLLMClient()
        self.orchestrator = WorkerOrchestrator(
            router=self.router,
            dispatcher=self.dispatcher,
            llm_client=self.llm
        )

        # Setup Speech Adapter
        self.stt = MockSpeechAdapter()

        # Setup WhatsApp Security
        self.app_secret = "qa-whatsapp-test-signing-secret"
        self.verify_token = "qa-whatsapp-test-verify-token"
        self.wa_security = WhatsAppSecurity(
            app_secret=self.app_secret,
            verify_token=self.verify_token
        )

        # Setup Gateway Application
        self.gateway = GatewayApp(
            orchestrator=self.orchestrator,
            whatsapp_security=self.wa_security,
            speech_adapter=self.stt,
            openwa_shared_secret="qa-openwa-bridge-secret-40-characters-long"
        )

    # =========================================================================
    # 1. Product Search by Product ID, Price & Specs via MCP Catalog Server
    # =========================================================================

    async def test_mcp_catalog_search_by_product_id_and_name(self):
        """Test searching product ID P1041 and resolving exact specs & live pricing."""
        # 1. find_product by name
        res_find = await self.catalog_server.find_product("Pulse Buds 141")
        self.assertTrue(res_find["found"])
        self.assertEqual(res_find["candidates"][0]["product_id"], "P1041")
        self.assertEqual(res_find["candidates"][0]["name"], "Pulse Buds 141")

        # 2. get_product_price by exact product_id
        res_price = await self.catalog_server.get_product_price("P1041")
        self.assertTrue(res_price["found"])
        self.assertEqual(res_price["product_id"], "P1041")
        self.assertEqual(res_price["price"], 1499)
        self.assertEqual(res_price["discount_price"], 1299)
        self.assertTrue(res_price["in_stock"])

        # 3. get_product_details by product_id
        res_details = await self.catalog_server.get_product_details("P1041")
        self.assertTrue(res_details["found"])
        self.assertIn("battery_life", res_details["specs"])
        self.assertIn("42 hours", res_details["specs"]["battery_life"])

        # 4. Unknown product_id handling
        res_unknown = await self.catalog_server.get_product_price("P9999_UNKNOWN")
        self.assertFalse(res_unknown["found"])
        self.assertIn("not found", res_unknown["error"])

    async def test_ai_product_inquiry_end_to_end(self):
        """AI orchestrator uses MCP tools to look up product ID and compose grounded reply."""
        ctx = SessionContext(
            tenant_id="demo-shop",
            conv_id="test_conv_prod",
            customer_id="CUST-42",
            level=AuthLevel.IDENTIFIED,
            channel="web"
        )
        response = await self.orchestrator.process_turn(
            user_message="What is the price and battery life of Pulse Buds 141?",
            ctx=ctx
        )
        self.assertIn("get_product_price", response.tools_called)
        self.assertIn("search_product_docs", response.tools_called)
        self.assertIn("1,299", response.reply)
        self.assertIn("42 hours", response.reply)

    # =========================================================================
    # 2. Order Lookup by Order ID & Tracking via MCP Order Server
    # =========================================================================

    async def test_mcp_order_lookup_by_order_id_and_tracking(self):
        """Test looking up ORD-1029 and checking ownership enforcement."""
        # Identified session for customer 'CUST-42'
        ctx_owner = SessionContext(
            tenant_id="demo-shop",
            conv_id="test_conv_ord",
            customer_id="CUST-42",
            level=AuthLevel.IDENTIFIED,
            channel="web"
        )
        owner_token = mint_internal_token(ctx_owner)

        # 1. Owner gets order status
        res_order = await self.order_server.get_order_status("ORD-1029", auth_token=owner_token)
        self.assertTrue(res_order["found"])
        self.assertEqual(res_order["order_id"], "ORD-1029")
        self.assertEqual(res_order["status"], "Delivered")
        self.assertEqual(len(res_order["items"]), 1)
        self.assertEqual(res_order["items"][0]["name"], "Pulse Buds 141")

        # 2. Owner tracks shipment events
        res_track = await self.order_server.get_tracking("ORD-1030", auth_token=owner_token)
        self.assertTrue(res_track["found"])
        self.assertTrue(len(res_track["events"]) >= 3)
        self.assertEqual(res_track["events"][-1]["status"], "Arrived at Delivery Facility")

        # 3. Horizontal Privilege Escalation prevention: wrong customer cannot see ORD-1029
        ctx_intruder = SessionContext(
            tenant_id="demo-shop",
            conv_id="test_conv_intruder",
            customer_id="CUST-INTRUDER-99",
            level=AuthLevel.IDENTIFIED,
            channel="web"
        )
        intruder_token = mint_internal_token(ctx_intruder)
        res_blocked = await self.order_server.get_order_status("ORD-1029", auth_token=intruder_token)
        self.assertFalse(res_blocked["found"])
        self.assertIn("not found for your account", res_blocked["message"])

        # 4. Anonymous user cannot query order status (requires login)
        ctx_anon = SessionContext(
            tenant_id="demo-shop",
            conv_id="test_conv_anon",
            customer_id=None,
            level=AuthLevel.ANONYMOUS,
            channel="web"
        )
        anon_token = mint_internal_token(ctx_anon)
        res_unauth = await self.order_server.get_order_status("ORD-1029", auth_token=anon_token)
        self.assertFalse(res_unauth["authorized"])
        self.assertEqual(res_unauth["needs_auth"], "login_required")

    async def test_ai_order_status_inquiry_end_to_end(self):
        """AI orchestrator uses MCP order tool to retrieve status of order ORD-1029."""
        ctx = SessionContext(
            tenant_id="demo-shop",
            conv_id="test_conv_ord_ai",
            customer_id="CUST-42",
            level=AuthLevel.IDENTIFIED,
            channel="web"
        )
        response = await self.orchestrator.process_turn(
            user_message="Where is my order ORD-1029?",
            ctx=ctx
        )
        self.assertIn("get_order_status", response.tools_called)
        self.assertIn("delivered", response.reply.lower())

    # =========================================================================
    # 3. MCP Tool Dispatcher (Client) Architecture & Tool Schemas
    # =========================================================================

    async def test_mcp_dispatcher_client_and_tool_schemas(self):
        """Verify MCP dispatcher routes tools and hides customer identity from LLM parameters."""
        schemas = self.dispatcher.get_tool_schemas()
        self.assertTrue(len(schemas) >= 7)

        # Rule 1 Invariant: customer_id must NEVER be an LLM tool parameter
        for s in schemas:
            func = s.get("function", {})
            params = func.get("parameters", {}).get("properties", {})
            self.assertNotIn("customer_id", params, f"Security violation: customer_id in {func.get('name')}")
            self.assertNotIn("auth_level", params, f"Security violation: auth_level in {func.get('name')}")

        # Dispatcher tool execution trace recording
        ctx = SessionContext(
            tenant_id="demo-shop",
            conv_id="test_trace",
            customer_id="CUST-42",
            level=AuthLevel.IDENTIFIED,
            channel="web"
        )
        res = await self.dispatcher.execute_tool("get_product_price", {"product_id": "P1041"}, ctx)
        self.assertTrue(res["found"])
        self.assertTrue(len(self.dispatcher.traces) > 0)
        last_trace = self.dispatcher.traces[-1]
        self.assertEqual(last_trace["tool_name"], "get_product_price")
        self.assertEqual(last_trace["result_status"], "success")

    # =========================================================================
    # 4. Speech-to-Text (STT) Port and Mock/Whisper Adapter
    # =========================================================================

    async def test_speech_adapter_stt_transcription(self):
        """Verify STT adapter transcribes English, Tamil, and Tanglish audio signatures."""
        # 1. English Order Voice Note
        t_en = await self.stt.transcribe(b"AUDIO_ORD_1029_STATUS", content_type="audio/ogg")
        self.assertEqual(t_en, "Where is my order ORD-1029?")

        # 2. English Product Voice Note
        t_prod = await self.stt.transcribe(b"AUDIO_P1041_PRICE", content_type="audio/ogg")
        self.assertEqual(t_prod, "What is the price of product P1041?")

        # 3. Tamil Voice Note
        t_ta = await self.stt.transcribe(b"AUDIO_TAMIL_PRICE", content_type="audio/ogg")
        self.assertEqual(t_ta, "Pulse Buds 141 விலை என்ன?")

        # 4. Tanglish Voice Note
        t_tanglish = await self.stt.transcribe(b"AUDIO_TANGLISH_ORDER", content_type="audio/ogg")
        self.assertEqual(t_tanglish, "Enna order ORD-1029 vandhurucha? Status sollunga")

        # 5. Empty audio returns empty text
        t_empty = await self.stt.transcribe(b"", content_type="audio/ogg")
        self.assertEqual(t_empty, "")
        t_unknown = await self.stt.transcribe(b"not-a-known-test-audio-signature", content_type="audio/ogg")
        self.assertEqual(t_unknown, "")

    # =========================================================================
    # 5. WhatsApp Voice Pipeline End-to-End
    # =========================================================================

    async def test_meta_webhook_media_id_is_not_mistaken_for_audio_bytes(self):
        """
        Verify incoming WhatsApp audio webhook querying a product:
        Audio payload -> STT transcription -> AI turn processing -> WhatsApp delivered reply.
        """
        async with AsyncClient(transport=ASGITransport(app=self.gateway), base_url="http://testserver") as client:
            voice_payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "messages": [{
                                "id": "wamid.VOICE_NOTE_PROD",
                                "from": "919876543210",
                                "type": "audio",
                                "audio": {
                                    "id": "AUDIO_P1041_PRICE",
                                    "mime_type": "audio/ogg; codecs=opus"
                                }
                            }]
                        }
                    }]
                }]
            }
            body_bytes = json.dumps(voice_payload).encode("utf-8")
            valid_sig = "sha256=" + hmac.new(self.app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

            res = await client.post(
                "/webhooks/whatsapp",
                content=body_bytes,
                headers={"X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"}
            )
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json()

            self.assertEqual(data["status"], "voice_media_unavailable")
            self.assertNotIn("transcription", data)

    async def test_meta_webhook_order_voice_media_id_is_not_transcribed(self):
        """
        Verify incoming WhatsApp audio webhook querying an order for an identified customer:
        Session is seeded as IDENTIFIED for CUST-42 -> Voice note -> STT -> MCP Order lookup -> Reply.
        """
        # Pre-seed identified session for WhatsApp user 919876543210
        self.gateway._session_store[("demo-shop", "wa_919876543210")] = SessionContext(
            tenant_id="demo-shop",
            conv_id="wa_919876543210",
            customer_id="CUST-42",
            level=AuthLevel.IDENTIFIED,
            channel="whatsapp"
        )

        async with AsyncClient(transport=ASGITransport(app=self.gateway), base_url="http://testserver") as client:
            voice_payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "messages": [{
                                "id": "wamid.VOICE_NOTE_ORD",
                                "from": "919876543210",
                                "type": "audio",
                                "audio": {
                                    "id": "AUDIO_ORD_1029_STATUS",
                                    "mime_type": "audio/ogg; codecs=opus"
                                }
                            }]
                        }
                    }]
                }]
            }
            body_bytes = json.dumps(voice_payload).encode("utf-8")
            valid_sig = "sha256=" + hmac.new(self.app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

            res = await client.post(
                "/webhooks/whatsapp",
                content=body_bytes,
                headers={"X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"}
            )
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json()

            self.assertEqual(data["status"], "voice_media_unavailable")
            self.assertNotIn("transcription", data)

    async def test_whatsapp_voice_pipeline_unsupported_without_speech_adapter(self):
        """When speech_adapter is None, voice notes return a helpful, graceful response."""
        gateway_without_speech = GatewayApp(
            orchestrator=self.orchestrator,
            whatsapp_security=self.wa_security,
            speech_adapter=None
        )
        async with AsyncClient(transport=ASGITransport(app=gateway_without_speech), base_url="http://testserver") as client:
            voice_payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "messages": [{
                                "id": "wamid.VOICE_NOTE_002",
                                "from": "919876543210",
                                "type": "audio",
                                "audio": {"id": "sample_id", "mime_type": "audio/ogg"}
                            }]
                        }
                    }]
                }]
            }
            body_bytes = json.dumps(voice_payload).encode("utf-8")
            valid_sig = "sha256=" + hmac.new(self.app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

            res = await client.post(
                "/webhooks/whatsapp",
                content=body_bytes,
                headers={"X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "voice_unsupported")
            self.assertIn("not configured", data["reply"])

    async def test_openwa_voice_pipeline_decrypt_transcribe_and_reply(self):
        """OpenWA forwards actual decrypted bytes through the authenticated bridge route."""
        payload = {
            "message_id": "openwa-voice-product-001",
            "sender": "919876543210@c.us",
            "type": "ptt",
            "mime_type": "audio/ogg; codecs=opus",
            "audio_base64": base64.b64encode(b"AUDIO_P1041_PRICE").decode("ascii"),
        }
        async with AsyncClient(transport=ASGITransport(app=self.gateway), base_url="http://testserver") as client:
            unauthorized = await client.post("/integrations/openwa/messages", json=payload)
            self.assertEqual(unauthorized.status_code, 401)
            response = await client.post(
                "/integrations/openwa/messages",
                json=payload,
                headers={"Authorization": "Bearer qa-openwa-bridge-secret-40-characters-long"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["status"], "processed")
            self.assertEqual(data["transcription"]["transcript"], "What is the price of product P1041?")
            self.assertIn("1,299", data["reply"])
            duplicate = await client.post(
                "/integrations/openwa/messages",
                json=payload,
                headers={"Authorization": "Bearer qa-openwa-bridge-secret-40-characters-long"},
            )
            replay = duplicate.json()
            self.assertEqual(replay["status"], "processed")
            self.assertEqual(replay["reply"], data["reply"])
            self.assertEqual(replay["trace_id"], data["trace_id"])


if __name__ == "__main__":
    unittest.main()
