"""
Integration tests for MockShop Adapters
Validates compliance with CatalogPort, OrderPort, and RefundPort.
Uses zero-socket sync driving for deterministic sandbox execution.
"""

import unittest
import sys
from pathlib import Path

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import RefundState
from adapters.mockshop import MockCatalogAdapter, MockOrderAdapter, MockRefundAdapter


def run_sync(coro):
    """Drive in-memory coroutines to completion without loopback socket dependencies."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value


class TestMockShopAdapters(unittest.TestCase):

    def setUp(self):
        self.catalog = MockCatalogAdapter()
        self.orders = MockOrderAdapter()
        self.refunds = MockRefundAdapter(self.orders, auto_limit_inr=2000)

    def test_catalog_exact_and_lookalike_search(self):
        # 1. Exact model query
        matches = run_sync(self.catalog.find_product("Pulse Buds 141"))
        self.assertTrue(len(matches) >= 1)
        self.assertEqual(matches[0].product_id, "P1041")
        self.assertGreaterEqual(matches[0].score, 0.90)

        # 2. Look-alike broad query (Pulse Buds)
        matches_broad = run_sync(self.catalog.find_product("Pulse Buds"))
        p_ids = [m.product_id for m in matches_broad]
        self.assertIn("P1041", p_ids)
        self.assertIn("P1031", p_ids)  # Both look-alikes captured for disambiguation

    def test_catalog_get_details_and_live_price(self):
        specs = run_sync(self.catalog.get_details("P1041"))
        self.assertIsNotNone(specs)
        self.assertEqual(specs.name, "Pulse Buds 141")
        self.assertIn("42 hours", specs.specs["battery_life"])

        price_info = run_sync(self.catalog.get_price("P1041"))
        self.assertIsNotNone(price_info)
        self.assertEqual(price_info.price, 1499)
        self.assertEqual(price_info.discount_price, 1299)
        self.assertTrue(price_info.in_stock)

    def test_catalog_search_product_docs_confined(self):
        docs = run_sync(self.catalog.search_product_docs("P1041", "battery playtime"))
        self.assertTrue(len(docs) > 0)
        # Verify no chunks from P1031 (Buds 131) leak
        for d in docs:
            self.assertIn("Pulse Buds 141", d)
            self.assertNotIn("Pulse Buds 131", d)

    def test_order_lookup_with_ownership_enforcement(self):
        # Owned order
        order = run_sync(self.orders.get_order("CUST-42", "ORD-1029"))
        self.assertIsNotNone(order)
        self.assertEqual(order.order_id, "ORD-1029")
        self.assertEqual(order.total_amount_inr, 1499)

        # Unowned order (cross-account) -> None
        unowned = run_sync(self.orders.get_order("CUST-42", "ORD-9999"))
        self.assertIsNone(unowned)

    def test_order_tracking_events(self):
        tracking = run_sync(self.orders.get_tracking("CUST-42", "ORD-1030"))
        self.assertEqual(len(tracking), 3)
        self.assertEqual(tracking[0].status, "Manifest Created")
        self.assertEqual(tracking[-1].status, "Arrived at Delivery Facility")

    def test_refund_under_2000_processed(self):
        result = run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-5501",
            amount_inr=1499,
            reason="earbuds defective",
            idempotency_key="idem_test_001"
        ))
        self.assertEqual(result.state, RefundState.PROCESSED)
        self.assertIn("approved automatically", result.message)

    def test_refund_over_2000_pending_approval(self):
        result = run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-8812",
            amount_inr=4500,
            reason="smartwatch screen frozen",
            idempotency_key="idem_test_002"
        ))
        self.assertEqual(result.state, RefundState.PENDING_APPROVAL)
        self.assertIn("exceeds the instant auto-refund limit", result.message)

    def test_refund_idempotency_replay(self):
        res1 = run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-5501",
            amount_inr=1499,
            reason="duplicate test",
            idempotency_key="idem_replay_key"
        ))
        res2 = run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-5501",
            amount_inr=1499,
            reason="duplicate test",
            idempotency_key="idem_replay_key"
        ))
        self.assertEqual(res1.refund_id, res2.refund_id)
        self.assertEqual(res1.created_at, res2.created_at)

    def test_refund_digital_goods_rejection(self):
        result = run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-7721",
            amount_inr=500,
            reason="accidental purchase",
            idempotency_key="idem_digi_001"
        ))
        self.assertEqual(result.state, RefundState.REJECTED)
        self.assertIn("category excluded by the configured store", result.message)

    def test_staff_decision_recording(self):
        # 1. Submit > ₹2000 refund -> PENDING_APPROVAL
        pending = run_sync(self.refunds.request_refund(
            customer_id="CUST-42",
            order_id="ORD-8812",
            amount_inr=4500,
            reason="screen frozen",
            idempotency_key="idem_staff_test"
        ))
        self.assertEqual(pending.state, RefundState.PENDING_APPROVAL)

        # 2. Staff approves via Support Desk
        approved = run_sync(self.refunds.record_staff_decision(
            refund_id=pending.refund_id,
            state=RefundState.APPROVED,
            decided_by="supervisor@novaretail.com",
            note="Verified hardware failure logs with manufacturer."
        ))
        self.assertEqual(approved.state, RefundState.APPROVED)
        self.assertEqual(approved.decided_by, "supervisor@novaretail.com")
        self.assertIsNotNone(approved.decided_at)


if __name__ == "__main__":
    unittest.main()
