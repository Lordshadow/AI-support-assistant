"""Tenant-scoped staff search and read-only order lookup endpoints."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select

from db.models import ConversationSession, Escalation, OrderItemModel, OrderModel, RefundRequest
from db.session import get_async_session
from services.dashboard_api.dependencies import StaffSessionContext, get_current_staff, require_roles

router = APIRouter(prefix="/api/admin/v1", tags=["search"])


@router.get("/search")
async def search_records(
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    staff: StaffSessionContext = Depends(get_current_staff),
) -> dict[str, list[dict[str, Any]]]:
    term = f"%{q.strip()}%"
    if len(q.strip()) < 2:
        return {"results": []}
    results: list[dict[str, Any]] = []
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        refund_rows = (await session.execute(
            select(RefundRequest).where(
                RefundRequest.tenant_id == staff.tenant_id,
                or_(RefundRequest.refund_id.ilike(term), RefundRequest.order_id.ilike(term)),
                RefundRequest.state == "pending_approval",
            ).order_by(RefundRequest.request_time.desc()).limit(limit)
        )).scalars().all()
        for row in refund_rows:
            results.append({"id": row.refund_id, "type": "refund", "title": f"Refund {row.refund_id}",
                            "subtitle": f"Order {row.order_id} · {row.state}", "path": f"/refunds?refund_id={row.refund_id}"})

        escalation_rows = (await session.execute(
            select(Escalation).where(
                Escalation.tenant_id == staff.tenant_id,
                or_(Escalation.esc_id.ilike(term), Escalation.conv_id.ilike(term)),
            ).order_by(Escalation.created_at.desc()).limit(limit)
        )).scalars().all()
        for row in escalation_rows:
            results.append({"id": row.esc_id, "type": "escalation", "title": f"Escalation {row.esc_id}",
                            "subtitle": f"{row.state} · {row.priority}", "path": f"/escalations?esc_id={row.esc_id}"})

        if staff.role in {"executive", "manager"}:
            conversation_rows = (await session.execute(
                select(ConversationSession).where(
                    ConversationSession.tenant_id == staff.tenant_id,
                    ConversationSession.conv_id.ilike(term),
                ).order_by(ConversationSession.last_user_message_at.desc()).limit(limit)
            )).scalars().all()
            for row in conversation_rows:
                results.append({"id": row.conv_id, "type": "conversation", "title": f"Conversation {row.conv_id}",
                                "subtitle": f"{row.channel} · {row.handoff_state}", "path": f"/conversations?conv_id={row.conv_id}"})

        if staff.role in {"manager", "admin"}:
            order_rows = (await session.execute(
                select(OrderModel).where(
                    OrderModel.tenant_id == staff.tenant_id,
                    OrderModel.order_id.ilike(term),
                ).order_by(OrderModel.created_at.desc()).limit(limit)
            )).scalars().all()
            for row in order_rows:
                results.append({"id": row.order_id, "type": "order", "title": f"Order {row.order_id}",
                                "subtitle": f"{row.status} · Customer {row.customer_id}", "path": f"/orders?order_id={row.order_id}"})

    return {"results": results[:limit]}


@router.get("/orders/{order_id}")
async def get_order_detail(
    order_id: str,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
) -> dict[str, Any]:
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        order = (await session.execute(select(OrderModel).where(
            OrderModel.tenant_id == staff.tenant_id,
            OrderModel.order_id == order_id,
        ))).scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found.")
        items = (await session.execute(select(OrderItemModel).where(OrderItemModel.order_id == order_id))).scalars().all()
        return {
            "order_id": order.order_id,
            "status": order.status,
            "total_amount_inr": str(order.total_amount_inr),
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
            "items": [{"product_name": item.product_name, "quantity": item.quantity,
                       "price_inr": str(item.price), "category": item.category} for item in items],
        }
