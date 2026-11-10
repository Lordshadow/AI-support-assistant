"""
PostgreSQL Implementation of OrderPort.
Complies with Specification Section 6 and Section 10.
"""

import os
import logging
import httpx
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.ports import OrderPort
from core.models import Order, OrderItem, OrderStatus, TrackingEvent
from db.models import OrderModel, OrderItemModel
from db.session import get_async_session

logger = logging.getLogger(__name__)


class PostgresOrderRepository:
    """Implements OrderPort using PostgreSQL with tenant context and live store fallback."""

    def __init__(
        self,
        tenant_id: str = "tenant_novaretail",
        session_factory=None,
        store_api_url: Optional[str] = None,
        store_api_token: Optional[str] = None,
    ):
        self.tenant_id = tenant_id
        self._session_factory = session_factory
        self.store_api_url = (store_api_url or os.getenv("APEXSTORE_CATALOG_API_URL", "")).rstrip("/")
        self.store_api_token = store_api_token or os.getenv("APEXSTORE_CATALOG_API_TOKEN", "")

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
                refund_eligibility_verified=getattr(it, "refund_eligibility_verified", True),
            )
            for it in (row.items or [])
        ]
        return Order(
            order_id=row.order_id,
            customer_id=row.customer_id,
            items=items,
            total_amount_inr=row.total_amount_inr,
            status=next((value for value in OrderStatus if value.value.casefold() == str(row.status).casefold()), OrderStatus.UNKNOWN),
            created_at=row.created_at,
            delivered_at=row.delivered_at,
            tracking_number=row.tracking_number,
            courier_name=row.courier_name,
            shipping_address=row.shipping_address,
        )

    def _dict_to_domain(self, d: dict, customer_id: str) -> Order:
        oid = d["order_id"]
        source_customer_id = d.get("customer_id")
        if source_customer_id is not None and str(source_customer_id) != str(customer_id):
            raise ValueError("Store API returned an order owned by a different customer.")
        status_raw = str(d.get("status") or "").strip().casefold()
        status = next((value for value in OrderStatus if value.value.casefold() == status_raw), OrderStatus.UNKNOWN)

        def parse_amount(value: object) -> Decimal:
            try:
                amount = Decimal(str(value))
                return amount.quantize(Decimal("0.01")) if amount.is_finite() and amount >= 0 else Decimal("0.00")
            except (InvalidOperation, TypeError, ValueError):
                return Decimal("0.00")

        def parse_bool(value: object) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().casefold() in {"1", "true", "yes", "y"}
            return bool(value)

        created_str = d.get("created_at")
        try:
            created_at = datetime.fromisoformat(created_str.replace(" ", "T")) if created_str else datetime.now(timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        except Exception:
            created_at = datetime.now(timezone.utc)

        delivered_str = d.get("delivered_at")
        try:
            delivered_at = datetime.fromisoformat(delivered_str.replace(" ", "T")) if delivered_str else None
            if delivered_at.tzinfo is None:
                delivered_at = delivered_at.replace(tzinfo=timezone.utc)
        except Exception:
            delivered_at = None

        total = parse_amount(d.get("total", 0))

        items = []
        raw_items = d.get("items", [])
        for idx, it in enumerate(raw_items, 1):
            price = parse_amount(it.get("unit_price", it.get("price", 0)))
            category_raw = it.get("category")
            category = str(category_raw).strip() if category_raw else "unknown"
            digital_present = "is_digital" in it or "digital" in it
            is_digital = parse_bool(it.get("is_digital", it.get("digital", category.casefold() in {"digital", "gift card", "gift_card"})))
            try:
                quantity = int(it.get("quantity", 1))
            except (TypeError, ValueError):
                quantity = 0
            items.append(OrderItem(
                item_id=f"{oid}-ITM-{idx}",
                product_id=str(it.get("product_id") or it.get("id") or ""),
                product_name=it.get("name") or it.get("title") or "Item",
                category=category,
                price=price,
                quantity=quantity,
                is_digital=is_digital,
                is_refunded=parse_bool(it.get("is_refunded", it.get("refunded", False))),
                refund_eligibility_verified=quantity > 0 and ((bool(category_raw) and category.casefold() not in {"unknown", "n/a"}) or (digital_present and is_digital)),
            ))

        return Order(
            order_id=oid,
            customer_id=str(customer_id),
            items=items,
            total_amount_inr=total if total > 0 else sum((i.price * i.quantity for i in items), Decimal("0.00")),
            status=status,
            created_at=created_at,
            delivered_at=delivered_at,
            tracking_number=f"DELHIVERY-{oid[-4:]}",
            courier_name="Delhivery Express",
            shipping_address=d.get("shipping_address") or "Customer Shipping Address",
        )

    async def _save_order_to_db(self, order: Order) -> None:
        try:
            async with get_async_session(tenant_id=self.tenant_id) as session:
                existing = await session.get(OrderModel, order.order_id)
                if not existing:
                    session.add(OrderModel(
                        order_id=order.order_id,
                        tenant_id=self.tenant_id,
                        customer_id=order.customer_id,
                        total_amount_inr=order.total_amount_inr,
                        status=order.status.value,
                        tracking_number=order.tracking_number,
                        courier_name=order.courier_name,
                        shipping_address=order.shipping_address,
                        created_at=order.created_at,
                        delivered_at=order.delivered_at,
                    ))
                    for it in order.items:
                        session.add(OrderItemModel(
                            item_id=it.item_id,
                            order_id=order.order_id,
                            product_id=it.product_id,
                            product_name=it.product_name,
                            category=it.category,
                            price=it.price,
                            quantity=it.quantity,
                            is_digital=it.is_digital,
                            is_refunded=it.is_refunded,
                            refund_eligibility_verified=it.refund_eligibility_verified,
                        ))
                    await session.commit()
        except Exception as e:
            logger.warning("Error saving order %s to postgres: %s", order.order_id, e)

    async def _fetch_from_store_api(self, customer_id: str, order_id: str) -> Optional[Order]:
        if not self.store_api_url or not self.store_api_token:
            return None
        url = f"{self.store_api_url}/orders/{order_id}"
        headers = {"Authorization": f"Bearer {self.store_api_token}"}
        params = {"customer_id": customer_id}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url, headers=headers, params=params)
                if res.status_code != 200:
                    return None
                data = res.json()
                order_data = data.get("order")
                if not order_data:
                    return None
                dom = self._dict_to_domain(order_data, customer_id)
                await self._save_order_to_db(dom)
                return dom
        except Exception as e:
            logger.debug("Store API get_order fallback failed: %s", e)
            return None

    async def get_order(self, customer_id: str, order_id: str) -> Optional[Order]:
        cid = str(customer_id)
        oid = str(order_id).strip().upper()
        try:
            async with get_async_session(tenant_id=self.tenant_id) as session:
                stmt = (
                    select(OrderModel)
                    .options(selectinload(OrderModel.items))
                    .where(
                        OrderModel.tenant_id == self.tenant_id,
                        OrderModel.order_id == oid,
                    )
                )
                result = await session.execute(stmt)
                row = result.scalars().first()
                if row:
                    if str(row.customer_id) == cid:
                        return self._to_domain(row)
                    return None
        except Exception as e:
            logger.debug("PostgreSQL get_order failed: %s", e)

        # Fallback to store API
        return await self._fetch_from_store_api(cid, oid)

    async def list_recent_orders(self, customer_id: str, limit: int = 5) -> List[Order]:
        cid = str(customer_id)
        try:
            async with get_async_session(tenant_id=self.tenant_id) as session:
                stmt = (
                    select(OrderModel)
                    .options(selectinload(OrderModel.items))
                    .where(
                        OrderModel.tenant_id == self.tenant_id,
                        OrderModel.customer_id == cid,
                    )
                    .order_by(OrderModel.created_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()
                if rows:
                    return [self._to_domain(r) for r in rows]
        except Exception as e:
            logger.debug("PostgreSQL list_recent_orders failed: %s", e)

        # Fallback to store API
        if self.store_api_url and self.store_api_token:
            url = f"{self.store_api_url}/customers/{cid}/orders"
            headers = {"Authorization": f"Bearer {self.store_api_token}"}
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.get(url, headers=headers, params={"limit": limit})
                    if res.status_code == 200:
                        data = res.json()
                        orders_list = data.get("orders", [])
                        domains = []
                        for od in orders_list:
                            dom = self._dict_to_domain(od, cid)
                            await self._save_order_to_db(dom)
                            domains.append(dom)
                        if domains:
                            return domains
            except Exception as e:
                logger.debug("Store API list_recent_orders failed: %s", e)

        return []

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
