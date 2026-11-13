"""
Unit and Integration Tests for Router, Language Normalizer, and Cache Layer
Validates Specification Section 1.5 (R1), 3.3, 9.1, 11, and 12.
"""

import unittest
import sys
from pathlib import Path

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import SessionContext, AuthLevel
from core.router import (
    LanguageNormalizer, CacheService, TemplateResponder, AIRouter
)
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter
from services.mcp_servers import (
    MCPCatalogServer, MCPOrderServer, MCPRefundServer,
    MCPHandoffServer, MCPToolDispatcher
)


def run_sync(coro):
    """Drive in-memory coroutine without socket dependencies."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value


class TestRouterAndCache(unittest.TestCase):

    def setUp(self):
        self.cache = CacheService()
        self.catalog_adapter = MockCatalogAdapter()
        self.order_adapter = MockOrderAdapter()
        self.refund_adapter = MockRefundAdapter(self.order_adapter)

        self.dispatcher = MCPToolDispatcher(
            catalog_server=MCPCatalogServer(self.catalog_adapter),
            order_server=MCPOrderServer(self.order_adapter),
            refund_server=MCPRefundServer(self.refund_adapter),
            handoff_server=MCPHandoffServer()
        )

        self.router = AIRouter(cache_service=self.cache, dispatcher=self.dispatcher)
        self.ident_ctx = SessionContext(tenant_id="demo", conv_id="c1", customer_id="CUST-42", level=AuthLevel.IDENTIFIED)
        self.anon_ctx = SessionContext(tenant_id="demo", conv_id="c2", level=AuthLevel.ANONYMOUS)

    def test_language_detection(self):
        self.assertEqual(LanguageNormalizer.detect_language("Where is my order?"), "en")
        self.assertEqual(LanguageNormalizer.detect_language("என் ஆர்டர் எப்போது வரும்?"), "ta")
        self.assertEqual(LanguageNormalizer.detect_language("En order eppo deliver aagum? sollunga."), "tanglish")
        self.assertEqual(LanguageNormalizer.detect_language("Return panna enna policy irukku?"), "tanglish")
        self.assertEqual(LanguageNormalizer.detect_language("Refund eppo credit aagum?"), "tanglish")
        self.assertEqual(LanguageNormalizer.detect_language("Return panna mudiyuma?"), "tanglish")
        self.assertEqual(LanguageNormalizer.detect_language("What is the return policy?"), "en")

    def test_entity_extraction(self):
        norm = LanguageNormalizer.normalize("Refund ORD-5501 for ₹1,499 please")
        self.assertEqual(norm.extracted_order_id, "ORD-5501")
        self.assertEqual(norm.extracted_amount_inr, 1499)
        self.assertEqual(norm.language, "en")

    def test_cache_ttl_and_invalidation(self):
        key = CacheService.key_faq("P1041", "battery life")
        self.cache.set(key, "42 hours playback", ttl_seconds=300)
        self.assertEqual(self.cache.get(key), "42 hours playback")

        # Invalidation
        invalidated = self.cache.invalidate_product("P1041")
        self.assertEqual(invalidated, 1)
        self.assertIsNone(self.cache.get(key))

    def test_greeting_template_route(self):
        decision = run_sync(self.router.route_message("Vanakkam", self.anon_ctx))
        self.assertEqual(decision.route_type, "template")
        self.assertEqual(decision.intent, "greeting")
        self.assertIn("NovaRetail", decision.template_response)

    def test_order_status_template_route(self):
        # Identified user querying ORD-1029 status triggers zero-cost template
        decision = run_sync(self.router.route_message(
            "What is the status of my order ORD-1029?", self.ident_ctx
        ))
        self.assertEqual(decision.route_type, "template")
        self.assertEqual(decision.intent, "order_status")
        self.assertIn("Delivered", decision.template_response)
        self.assertIn("BlueDart Express", decision.template_response)

    def test_comparison_routes_to_large_model(self):
        decision = run_sync(self.router.route_message(
            "Compare Pulse Buds 141 vs Pulse Buds 131 specs", self.anon_ctx
        ))
        self.assertEqual(decision.route_type, "large_model")
        self.assertEqual(decision.intent, "product_comparison")

    def test_customer_dispute_routes_to_large_model(self):
        decision = run_sync(self.router.route_message(
            "This company is a scam and the product is terrible!", self.ident_ctx
        ))
        self.assertEqual(decision.route_type, "large_model")
        self.assertEqual(decision.intent, "customer_dispute")

    def test_human_handoff_route(self):
        decision = run_sync(self.router.route_message(
            "Please transfer me to a human executive", self.ident_ctx
        ))
        self.assertEqual(decision.route_type, "handoff")
        self.assertEqual(decision.intent, "human_handoff")

    def test_standard_faq_routes_to_small_model(self):
        decision = run_sync(self.router.route_message(
            "What is the return window for electronics?", self.anon_ctx
        ))
        self.assertEqual(decision.route_type, "small_model")
        self.assertEqual(decision.intent, "refund_request")

    def test_tanglish_policy_question_uses_model_path_not_policy_template(self):
        decision = run_sync(self.router.route_message(
            "Return panna enna policy irukku?", self.anon_ctx
        ))
        self.assertEqual(decision.route_type, "small_model")
        self.assertEqual(decision.normalized.language, "tanglish")
        self.assertIsNone(decision.template_response)

    def test_refund_action_does_not_use_policy_template(self):
        decision = run_sync(self.router.route_message("refund", self.ident_ctx))
        self.assertNotEqual(decision.route_type, "template")
        self.assertNotIn("specific order", decision.template_response or "")


if __name__ == "__main__":
    unittest.main()
