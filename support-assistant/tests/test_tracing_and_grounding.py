"""
Unit and Integration Tests for PII Masking, Grounding Verification, and Trace Collection
Validates Specification Section 9.2, 14 (R5 Explainability), and 15.1.11.
"""

import unittest
import sys
from pathlib import Path

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.tracing import (
    PIIMasker, GroundingVerifier, GroundingResult,
    TraceCollector, TurnTrace
)


class TestTracingAndGrounding(unittest.TestCase):

    def setUp(self):
        self.collector = TraceCollector()

    def test_pii_masking_emails_phones_cards(self):
        # Email
        self.assertEqual(PIIMasker.mask_email("customer42@novaretail.com"), "c***2@novaretail.com")

        # Phone
        self.assertEqual(PIIMasker.mask_phone("9876543210"), "******3210")
        self.assertEqual(PIIMasker.mask_phone("+91 9876543210"), "+91 ******3210")

        # Credit Card
        self.assertEqual(PIIMasker.mask_card("4111-2222-3333-4444"), "****-****-****-4444")

        # Text with multiple PII entities
        raw_text = "Contact customer42@gmail.com on 9876543210 regarding card 4111-2222-3333-4444 with OTP code 882190"
        masked = PIIMasker.mask_text(raw_text)
        self.assertNotIn("customer42@gmail.com", masked)
        self.assertNotIn("9876543210", masked)
        self.assertNotIn("4111-2222-3333-4444", masked)
        self.assertIn("****-****-****-4444", masked)

    def test_grounding_verifier_valid_facts_pass(self):
        draft = "The Pulse Buds 141 is priced at ₹1,499 and provides 42 hours of battery playback."
        tool_results = [
            {"product_id": "P1041", "price": 1499, "currency": "INR"},
            {"product_id": "P1041", "battery_life": "42 hours total playback"}
        ]
        chunks = ["Pulse Buds 141 - Battery life: 42 hours playback time"]

        res = GroundingVerifier.verify(draft, tool_results, chunks)
        self.assertTrue(res.passed)
        self.assertEqual(len(res.violations), 0)
        self.assertEqual(res.suggested_action, "allow")

    def test_grounding_verifier_hallucinated_price_fails(self):
        # Hallucinated price ₹9,999 not present in tools
        draft = "The Pulse Buds 141 costs ₹9,999 on our store."
        tool_results = [{"product_id": "P1041", "price": 1499}]

        res = GroundingVerifier.verify(draft, tool_results)
        self.assertFalse(res.passed)
        self.assertTrue(any("Ungrounded price claim" in v for v in res.violations))

    def test_grounding_verifier_unbacked_refund_claim_fails(self):
        # Claiming refund was approved when tool only returned an error or pending
        draft = "Your refund has been approved automatically and sent to your bank."
        tool_results = [{"order_id": "ORD-101", "state": "pending_approval"}]

        res = GroundingVerifier.verify(draft, tool_results)
        self.assertFalse(res.passed)
        self.assertTrue(any("Ungrounded refund claim" in v for v in res.violations))

    def test_grounding_verifier_pii_leak_rejected(self):
        # Model echoes a customer's raw credit card
        draft = "We have credited the amount to card 4111-2222-3333-4444."
        tool_results = [{"state": "processed"}]

        res = GroundingVerifier.verify(draft, tool_results)
        self.assertFalse(res.passed)
        self.assertTrue(any("Data privacy violation" in v for v in res.violations))

    def test_trace_collector_records_turn_conforming_to_spec(self):
        grounding = GroundingResult(passed=True, violations=[])
        trace = self.collector.record_turn(
            conv_id="conv_1001",
            customer_message="Where is my order for customer42@gmail.com?",
            detected_language="en",
            route_type="small_model",
            intent="order_status",
            auth_level="identified",
            final_reply="Your order ORD-1029 is Delivered.",
            resolved_product_id="P1041",
            tool_calls=[{"tool_name": "get_order_status", "status": "success"}],
            model_used="llama-3.1-8b-instant",
            latency_ms=142.5,
            grounding_result=grounding
        )

        self.assertIsInstance(trace, TurnTrace)
        self.assertTrue(trace.trace_id.startswith("trc_"))
        self.assertEqual(trace.auth_level, "identified")
        self.assertEqual(trace.model_used, "llama-3.1-8b-instant")
        # Ensure email in user message was masked before recording
        self.assertNotIn("customer42@gmail.com", trace.customer_message)
        self.assertIn("c***2@gmail.com", trace.customer_message)

    def test_why_this_answer_view_structure(self):
        grounding = GroundingResult(passed=True, violations=[])
        trace = self.collector.record_turn(
            conv_id="conv_2002",
            customer_message="What is the battery of Pulse Buds 141?",
            detected_language="en",
            route_type="small_model",
            intent="product_faq",
            auth_level="anonymous",
            final_reply="It offers 42 hours of playback.",
            resolved_product_id="P1041",
            retrieved_chunk_ids=["chk_01", "chk_02"],
            tool_calls=[{"tool_name": "get_product_price", "arguments": {"product_id": "P1041"}}],
            model_used="llama-3.1-8b-instant",
            latency_ms=88.2,
            grounding_result=grounding
        )

        why_view = self.collector.get_why_this_answer(trace.trace_id)
        self.assertIsNotNone(why_view)
        self.assertEqual(why_view["trace_id"], trace.trace_id)
        self.assertEqual(why_view["routing_explanation"]["route_type"], "small_model")
        self.assertEqual(why_view["factual_grounding"]["resolved_product"], "P1041")
        self.assertTrue(why_view["factual_grounding"]["passed_gate"])
        self.assertIn("88.2 ms", why_view["latency"])


if __name__ == "__main__":
    unittest.main()
