"""
Unit tests for Core Domain Models & Policy Engine
Validates Specification Sections 1.3, 10, and 15.1.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import unittest
import sys
from pathlib import Path

# Add support-assistant to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    AuthLevel, SessionContext, Order, OrderItem, OrderStatus,
    RefundState, AuthLevelError, OwnershipError,
    require_level, verify_order_ownership, check_refund_eligibility,
    evaluate_refund_state, generate_idempotency_key
)


class TestCorePolicyEngine(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
        self.valid_delivered_at = self.now - timedelta(days=10)
        self.expired_delivered_at = self.now - timedelta(days=35)

        self.sample_order = Order(
            order_id="ORD-101",
            customer_id="CUST-42",
            items=[
                OrderItem(
                    item_id="ITM-1",
                    product_id="P1041",
                    product_name="Pulse Buds 141",
                    category="electronics",
                    price=1499,
                    quantity=1
                )
            ],
            total_amount_inr=1499,
            status=OrderStatus.DELIVERED,
            created_at=self.valid_delivered_at - timedelta(days=2),
            delivered_at=self.valid_delivered_at
        )

    def test_auth_level_hierarchy(self):
        self.assertTrue(AuthLevel.VERIFIED.satisfies(AuthLevel.IDENTIFIED))
        self.assertTrue(AuthLevel.VERIFIED.satisfies(AuthLevel.ANONYMOUS))
        self.assertTrue(AuthLevel.IDENTIFIED.satisfies(AuthLevel.ANONYMOUS))
        self.assertFalse(AuthLevel.IDENTIFIED.satisfies(AuthLevel.VERIFIED))
        self.assertFalse(AuthLevel.ANONYMOUS.satisfies(AuthLevel.IDENTIFIED))

    def test_require_level_enforcement(self):
        anon_ctx = SessionContext(tenant_id="demo", conv_id="c1", level=AuthLevel.ANONYMOUS)
        with self.assertRaises(AuthLevelError):
            require_level(anon_ctx, AuthLevel.IDENTIFIED)

        ident_ctx = SessionContext(tenant_id="demo", conv_id="c1", customer_id="CUST-42", level=AuthLevel.IDENTIFIED)
        # Should not raise for identified or anonymous
        require_level(ident_ctx, AuthLevel.IDENTIFIED)
        require_level(ident_ctx, AuthLevel.ANONYMOUS)
        with self.assertRaises(AuthLevelError):
            require_level(ident_ctx, AuthLevel.VERIFIED)

        verif_ctx = SessionContext(tenant_id="demo", conv_id="c1", customer_id="CUST-42", level=AuthLevel.VERIFIED)
        require_level(verif_ctx, AuthLevel.VERIFIED)

    def test_verify_order_ownership(self):
        valid_ctx = SessionContext(tenant_id="demo", conv_id="c1", customer_id="CUST-42", level=AuthLevel.IDENTIFIED)
        verify_order_ownership(valid_ctx, self.sample_order)  # Success

        invalid_ctx = SessionContext(tenant_id="demo", conv_id="c1", customer_id="ATTACKER-99", level=AuthLevel.IDENTIFIED)
        with self.assertRaises(OwnershipError):
            verify_order_ownership(invalid_ctx, self.sample_order)

    def test_eligibility_within_30_days(self):
        eligible, reason, amount = check_refund_eligibility(
            self.sample_order, current_time=self.now
        )
        self.assertTrue(eligible)
        self.assertEqual(amount, 1499)
        self.assertIn("meets all return window", reason)

    def test_eligibility_expired_window(self):
        expired_order = Order(
            order_id="ORD-102",
            customer_id="CUST-42",
            items=self.sample_order.items,
            total_amount_inr=1499,
            status=OrderStatus.DELIVERED,
            created_at=self.expired_delivered_at - timedelta(days=2),
            delivered_at=self.expired_delivered_at
        )
        eligible, reason, amount = check_refund_eligibility(
            expired_order, current_time=self.now
        )
        self.assertFalse(eligible)
        self.assertEqual(amount, 0)
        self.assertIn("Return window expired", reason)

    def test_eligibility_digital_goods_rejected(self):
        digital_order = Order(
            order_id="ORD-DIGITAL",
            customer_id="CUST-42",
            items=[
                OrderItem(
                    item_id="ITM-DIGI",
                    product_id="P-GIFT500",
                    product_name="Google Play ₹500 Code",
                    category="digital",
                    price=500,
                    is_digital=True
                )
            ],
            total_amount_inr=500,
            status=OrderStatus.DELIVERED,
            created_at=self.valid_delivered_at,
            delivered_at=self.valid_delivered_at
        )
        eligible, reason, amount = check_refund_eligibility(
            digital_order, current_time=self.now
        )
        self.assertFalse(eligible)
        self.assertEqual(amount, 0)
        self.assertIn("digital product / gift card and is non-refundable", reason)

    def test_eligibility_already_refunded_rejected(self):
        already_refunded_order = Order(
            order_id="ORD-REFUNDED",
            customer_id="CUST-42",
            items=[
                OrderItem(
                    item_id="ITM-REF",
                    product_id="P1041",
                    product_name="Pulse Buds 141",
                    category="electronics",
                    price=1499,
                    is_refunded=True
                )
            ],
            total_amount_inr=1499,
            status=OrderStatus.DELIVERED,
            created_at=self.valid_delivered_at,
            delivered_at=self.valid_delivered_at
        )
        eligible, reason, amount = check_refund_eligibility(
            already_refunded_order, current_time=self.now
        )
        self.assertFalse(eligible)
        self.assertIn("already been refunded", reason)

    def test_eligibility_undelivered_order_rejected(self):
        processing_order = Order(
            order_id="ORD-PROC",
            customer_id="CUST-42",
            items=self.sample_order.items,
            total_amount_inr=1499,
            status=OrderStatus.PROCESSING,
            created_at=self.now
        )
        eligible, reason, amount = check_refund_eligibility(
            processing_order, current_time=self.now
        )
        self.assertFalse(eligible)
        self.assertIn("can only be requested for delivered orders", reason)

    def test_unknown_item_metadata_fails_closed(self):
        item = OrderItem(
            item_id="ITM-UNKNOWN", product_id="X", product_name="Unclassified item",
            category="unknown", price=Decimal("1200.75"), refund_eligibility_verified=False
        )
        order = Order("ORD-UNKNOWN", "CUST-42", [item], Decimal("1200.75"), OrderStatus.DELIVERED,
                      self.valid_delivered_at, self.valid_delivered_at)
        eligible, reason, amount = check_refund_eligibility(order, current_time=self.now)
        self.assertFalse(eligible)
        self.assertEqual(amount, 0)
        self.assertIn("could not be verified", reason)

    def test_future_delivery_date_fails_closed(self):
        order = Order("ORD-FUTURE", "CUST-42", self.sample_order.items, 1499, OrderStatus.DELIVERED,
                      self.now, self.now + timedelta(days=1))
        eligible, reason, amount = check_refund_eligibility(order, current_time=self.now)
        self.assertFalse(eligible)
        self.assertEqual(amount, 0)
        self.assertIn("in the future", reason)

    def test_decimal_amount_and_idempotency_preserve_paise(self):
        item = OrderItem("ITM-PAISE", "X", "Camera", "electronics", Decimal("11188.82"))
        order = Order("ORD-PAISE", "CUST-42", [item], Decimal("11188.82"), OrderStatus.DELIVERED,
                      self.valid_delivered_at, self.valid_delivered_at)
        eligible, _, amount = check_refund_eligibility(order, current_time=self.now)
        self.assertTrue(eligible)
        self.assertEqual(amount, Decimal("11188.82"))
        self.assertNotEqual(
            generate_idempotency_key("t", "c", "o", Decimal("1999.99")),
            generate_idempotency_key("t", "c", "o", Decimal("2000.00")),
        )

    def test_evaluate_refund_state_under_limit(self):
        state = evaluate_refund_state(amount_inr=1499, auto_limit_inr=2000)
        self.assertEqual(state, RefundState.PROCESSED)

    def test_evaluate_refund_state_over_limit(self):
        state = evaluate_refund_state(amount_inr=4500, auto_limit_inr=2000)
        self.assertEqual(state, RefundState.PENDING_APPROVAL)

    def test_idempotency_key_consistency(self):
        k1 = generate_idempotency_key("demo", "CUST-42", "ORD-101", 1499)
        k2 = generate_idempotency_key("demo", "CUST-42", "ORD-101", 1499)
        k3 = generate_idempotency_key("demo", "CUST-42", "ORD-101", 1500)
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertTrue(k1.startswith("ref_idem_"))


if __name__ == "__main__":
    unittest.main()
