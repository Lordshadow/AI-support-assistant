"""
MockShop Order Adapter
Implements OrderPort protocol using realistic seed orders and shipping events.
Complies with Specification Section 6, 7.2, and 15.1 (Ownership enforcement).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from core.models import Order, OrderItem, OrderStatus, TrackingEvent


class MockOrderAdapter:
    """In-memory concrete implementation of OrderPort."""

    def __init__(self, base_time: Optional[datetime] = None):
        self.now = base_time or datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)

        # Seed orders covering all policy and edge cases
        self._orders: dict[str, Order] = {
            # 1. Eligible order under ₹2,000 (delivered 10 days ago)
            "ORD-1029": Order(
                order_id="ORD-1029",
                customer_id="CUST-42",
                items=[
                    OrderItem(
                        item_id="ITM-101",
                        product_id="P1041",
                        product_name="Pulse Buds 141",
                        category="electronics",
                        price=1499,
                        quantity=1
                    )
                ],
                total_amount_inr=1499,
                status=OrderStatus.DELIVERED,
                created_at=self.now - timedelta(days=13),
                delivered_at=self.now - timedelta(days=10),
                tracking_number="BLUEDART-88219",
                courier_name="BlueDart Express",
                shipping_address="42 Anna Salai, Chennai, TN - 600002"
            ),

            # 2. In-transit order (Shipped status)
            "ORD-1030": Order(
                order_id="ORD-1030",
                customer_id="CUST-42",
                items=[
                    OrderItem(
                        item_id="ITM-102",
                        product_id="P2001",
                        product_name="Nova Watch Pro",
                        category="wearables",
                        price=4500,
                        quantity=1
                    )
                ],
                total_amount_inr=4500,
                status=OrderStatus.SHIPPED,
                created_at=self.now - timedelta(days=2),
                tracking_number="DELHIVERY-77312",
                courier_name="Delhivery",
                shipping_address="42 Anna Salai, Chennai, TN - 600002"
            ),

            # 3. Eligible order under ₹2,000 for auto-refund
            "ORD-5501": Order(
                order_id="ORD-5501",
                customer_id="CUST-42",
                items=[
                    OrderItem(
                        item_id="ITM-103",
                        product_id="P1041",
                        product_name="Pulse Buds 141",
                        category="electronics",
                        price=1499,
                        quantity=1
                    )
                ],
                total_amount_inr=1499,
                status=OrderStatus.DELIVERED,
                created_at=self.now - timedelta(days=7),
                delivered_at=self.now - timedelta(days=5),
                tracking_number="EKART-11209",
                courier_name="Ekart Logistics",
                shipping_address="42 Anna Salai, Chennai, TN - 600002"
            ),

            # 4. Over ₹2,000 order (₹4,500) requiring supervisor approval
            "ORD-8812": Order(
                order_id="ORD-8812",
                customer_id="CUST-42",
                items=[
                    OrderItem(
                        item_id="ITM-104",
                        product_id="P2001",
                        product_name="Nova Watch Pro",
                        category="wearables",
                        price=4500,
                        quantity=1
                    )
                ],
                total_amount_inr=4500,
                status=OrderStatus.DELIVERED,
                created_at=self.now - timedelta(days=10),
                delivered_at=self.now - timedelta(days=8),
                tracking_number="BLUEDART-99014",
                courier_name="BlueDart Express",
                shipping_address="42 Anna Salai, Chennai, TN - 600002"
            ),

            # 5. Digital goods order (non-refundable under Policy 6.0)
            "ORD-7721": Order(
                order_id="ORD-7721",
                customer_id="CUST-42",
                items=[
                    OrderItem(
                        item_id="ITM-105",
                        product_id="P-GIFT500",
                        product_name="Google Play ₹500 Gift Card",
                        category="digital",
                        price=500,
                        quantity=1,
                        is_digital=True
                    )
                ],
                total_amount_inr=500,
                status=OrderStatus.DELIVERED,
                created_at=self.now - timedelta(days=4),
                delivered_at=self.now - timedelta(days=4),
                shipping_address="Email Delivery: cust42@example.com"
            ),

            # 6. Belongs to a different customer (for ownership violation tests)
            "ORD-9999": Order(
                order_id="ORD-9999",
                customer_id="CUST-99",
                items=[
                    OrderItem(
                        item_id="ITM-999",
                        product_id="P1041",
                        product_name="Pulse Buds 141",
                        category="electronics",
                        price=1499,
                        quantity=1
                    )
                ],
                total_amount_inr=1499,
                status=OrderStatus.DELIVERED,
                created_at=self.now - timedelta(days=1),
                delivered_at=self.now - timedelta(days=1),
                tracking_number="BLUEDART-12345",
                courier_name="BlueDart",
                shipping_address="10 MG Road, Bengaluru, KA"
            )
        }

        # Seed Tracking Events
        self._tracking: dict[str, list[TrackingEvent]] = {
            "ORD-1030": [
                TrackingEvent(
                    timestamp=self.now - timedelta(days=2),
                    location="Bengaluru Warehouse",
                    status="Manifest Created",
                    details="Item packed and shipping label generated."
                ),
                TrackingEvent(
                    timestamp=self.now - timedelta(days=1, hours=8),
                    location="Hosur Hub",
                    status="In Transit",
                    details="Package departed origin facility."
                ),
                TrackingEvent(
                    timestamp=self.now - timedelta(hours=4),
                    location="Chennai Hub",
                    status="Arrived at Delivery Facility",
                    details="Expected delivery tomorrow by 6:00 PM."
                )
            ]
        }

    async def get_order(self, customer_id: str, order_id: str) -> Optional[Order]:
        """
        Enforces ownership: returns order only if it belongs to customer_id.
        Returns None if not found or belongs to another customer (preventing enumeration).
        """
        order = self._orders.get(order_id)
        if not order:
            return None
        if order.customer_id != customer_id:
            return None
        return order

    async def list_recent_orders(self, customer_id: str, limit: int = 5) -> list[Order]:
        matching = [
            order for order in self._orders.values()
            if order.customer_id == customer_id
        ]
        matching.sort(key=lambda o: o.created_at, reverse=True)
        return matching[:limit]

    async def get_tracking(self, customer_id: str, order_id: str) -> list[TrackingEvent]:
        # First verify ownership
        order = await self.get_order(customer_id, order_id)
        if not order:
            return []
        return self._tracking.get(order_id, [])
