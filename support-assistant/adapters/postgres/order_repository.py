"""
PostgreSQL Implementation of OrderPort.
Complies with Specification Section 6 and Section 10.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.ports import OrderPort
from core.models import Order, OrderItem, OrderStatus, TrackingEvent
from db.models import OrderModel, OrderItemModel
from db.session import get_async_session


class PostgresOrderRepository:
    """Implements OrderPort using PostgreSQL with tenant context."""

    def __init__(self, tenant_id: str = "tenant_novaretail", session_factory=None):
        self.tenant_id = tenant_id
        self._session_factory = session_factory

    def _to_domain(self, row: OrderModel) -> Order:
        items = [
            OrderItem(
                item_id=it.item_id,
                product_id=it.product_id or "",
                product_name=it.product_name,
                category=it.category,
                price=it.price,
                quantity=it.quantity,
                is_digital=it.is_digital,
                is_refunded=it.is_refunded,
            )
            for it in (row.items or [])
        ]
        return Order(
            order_id=row.order_id,
            customer_id=row.customer_id,
            items=items,
            total_amount_inr=row.total_amount_inr,
            status=OrderStatus(row.status),
            created_at=row.created_at,
            delivered_at=row.delivered_at,
            tracking_number=row.tracking_number,
            courier_name=row.courier_name,
            shipping_address=row.shipping_address,
        )

    async def get_order(self, customer_id: str, order_id: str) -> Optional[Order]:
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = (
                select(OrderModel)
                .options(selectinload(OrderModel.items))
                .where(
                    OrderModel.tenant_id == self.tenant_id,
                    OrderModel.order_id == order_id,
                    OrderModel.customer_id == customer_id,
                )
            )
            result = await session.execute(stmt)
            row = result.scalars().first()
            if not row:
                return None
            return self._to_domain(row)

    async def list_recent_orders(self, customer_id: str, limit: int = 5) -> List[Order]:
        async with get_async_session(tenant_id=self.tenant_id) as session:
            stmt = (
                select(OrderModel)
                .options(selectinload(OrderModel.items))
                .where(
                    OrderModel.tenant_id == self.tenant_id,
                    OrderModel.customer_id == customer_id,
                )
                .order_by(OrderModel.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._to_domain(r) for r in rows]

    async def get_tracking(self, customer_id: str, order_id: str) -> List[TrackingEvent]:
        order = await self.get_order(customer_id, order_id)
        if not order:
            return []

        now = datetime.now(timezone.utc)
        events = [
            TrackingEvent(
                timestamp=order.created_at,
                location="Fulfillment Center",
                status="Order Placed",
                details="Order verified and scheduled for packing.",
            )
        ]

        if order.status in (OrderStatus.SHIPPED, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED):
            events.append(
                TrackingEvent(
                    timestamp=order.created_at + timedelta(hours=12),
                    location="Hub Central",
                    status="Manifest Created",
                    details=f"Dispatched via {order.courier_name or 'Courier'} ({order.tracking_number or 'AWB-PENDING'}).",
                )
            )
            events.append(
                TrackingEvent(
                    timestamp=order.created_at + timedelta(days=1),
                    location="Transit Hub",
                    status="In Transit",
                    details="Shipment arrived at destination distribution center.",
                )
            )

        if order.status in (OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED):
            events.append(
                TrackingEvent(
                    timestamp=order.created_at + timedelta(days=2),
                    location="Local Hub",
                    status="Out for Delivery",
                    details="Courier is out for delivery to destination address.",
                )
            )

        if order.status == OrderStatus.DELIVERED:
            delivered_ts = order.delivered_at or (order.created_at + timedelta(days=2, hours=4))
            events.append(
                TrackingEvent(
                    timestamp=delivered_ts,
                    location="Destination",
                    status="Delivered",
                    details="Package handed over to recipient.",
                )
            )

        return events
