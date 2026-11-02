"""
MCP Order Server (Read-Only)
Exposes customer order lookup and tracking.
Complies with Specification Section 7.2 and 15.1.
Enforces that identity comes strictly from the transport token, NEVER model arguments.
"""

from typing import Any
from core.ports import OrderPort
from core.models import AuthLevel
from services.mcp_servers.auth import ctx_from_token


class MCPOrderServer:
    """Tool server for Order operations."""

    def __init__(self, order_adapter: OrderPort):
        self.orders = order_adapter

    async def get_order_status(self, order_id: str, auth_token: str) -> dict[str, Any]:
        """Fetch order status for an owned order."""
        ctx = ctx_from_token(auth_token)
        if not ctx.level.satisfies(AuthLevel.IDENTIFIED):
            return {
                "authorized": False,
                "needs_auth": "login_required",
                "message": "You must be logged in to check order status."
            }

        order = await self.orders.get_order(ctx.customer_id, order_id)
        if not order:
            return {
                "found": False,
                "message": f"Order '{order_id}' was not found for your account."
            }

        return {
            "found": True,
            "order_id": order.order_id,
            "status": order.status.value,
            "total_amount_inr": order.total_amount_inr,
            "items": [
                {
                    "item_id": i.item_id,
                    "name": i.product_name,
                    "quantity": i.quantity,
                    "price": i.price
                }
                for i in order.items
            ],
            "tracking_number": order.tracking_number,
            "courier_name": order.courier_name,
            "created_at": order.created_at.strftime("%Y-%m-%d"),
            "delivered_at": order.delivered_at.strftime("%Y-%m-%d") if order.delivered_at else None
        }

    async def list_recent_orders(self, auth_token: str, limit: int = 5) -> dict[str, Any]:
        """List customer's recent orders."""
        ctx = ctx_from_token(auth_token)
        if not ctx.level.satisfies(AuthLevel.IDENTIFIED):
            return {
                "authorized": False,
                "needs_auth": "login_required",
                "message": "Please log in to view your recent orders."
            }

        orders = await self.orders.list_recent_orders(ctx.customer_id, limit=limit)
        return {
            "count": len(orders),
            "orders": [
                {
                    "order_id": o.order_id,
                    "status": o.status.value,
                    "total_amount_inr": o.total_amount_inr,
                    "item_names": [i.product_name for i in o.items],
                    "created_at": o.created_at.strftime("%Y-%m-%d")
                }
                for o in orders
            ]
        }

    async def get_tracking(self, order_id: str, auth_token: str) -> dict[str, Any]:
        """Fetch tracking events for an owned order."""
        ctx = ctx_from_token(auth_token)
        if not ctx.level.satisfies(AuthLevel.IDENTIFIED):
            return {
                "authorized": False,
                "needs_auth": "login_required",
                "message": "Please log in to track your order."
            }

        events = await self.orders.get_tracking(ctx.customer_id, order_id)
        if not events:
            return {"found": False, "message": f"No tracking events found for order '{order_id}'."}

        return {
            "found": True,
            "order_id": order_id,
            "events": [
                {
                    "timestamp": e.timestamp.strftime("%Y-%m-%d %H:%M"),
                    "location": e.location,
                    "status": e.status,
                    "details": e.details
                }
                for e in events
            ]
        }
