"""Authenticated refund review API used by the staff dashboard."""

from datetime import datetime, timezone
import hmac
import os
import uuid
from typing import Optional

import httpx

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from db.models import AuditEvent, OrderModel, RefundRequest
from db.session import get_async_session
from services.dashboard_api.dependencies import StaffSessionContext, require_roles

router = APIRouter(prefix="/api/admin/v1/refunds", tags=["refunds"])
legacy_router = APIRouter(tags=["legacy-refunds"])
integration_router = APIRouter(prefix="/api/internal/v1/refunds", tags=["refund-integrations"])


class RefundDecision(BaseModel):
    notes: str = ""


async def _review_store_refund(refund: RefundRequest, decision: str, notes: str) -> dict:
    url = os.getenv("APEXSTORE_REFUND_SYNC_URL", "").strip()
    secret = os.getenv("APEXSTORE_REFUND_SYNC_SECRET", "")
    if not url or not secret:
        raise HTTPException(status_code=503, detail="Store refund synchronization is not configured.")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {secret}"},
                json={
                    "order_id": refund.order_id,
                    "source_refund_id": refund.refund_id,
                    "decision": "Approved" if decision == "approved" else "Rejected",
                    "note": notes.strip(),
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Store refund service is unavailable; no decision was recorded.") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400 or payload.get("success") is not True:
        raise HTTPException(
            status_code=409 if response.status_code == 409 else 503,
            detail=payload.get("error", "Store refund could not be synchronized; no decision was recorded."),
        )
    return payload


def _require_step_up(staff: StaffSessionContext, amount_inr: int) -> None:
    if amount_inr > 5000:
        if staff.role == "executive":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Refunds exceeding ₹5,000 require Manager or Admin supervisory sign-off.",
            )
        if not staff.is_stepped_up:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Step-up authentication required.", "code": "STEP_UP_REQUIRED"},
            )


async def _list_pending(staff: StaffSessionContext):
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        result = await session.execute(
            select(RefundRequest)
            .where(
                RefundRequest.tenant_id == staff.tenant_id,
                RefundRequest.state == "pending_approval",
            )
            .order_by(RefundRequest.request_time.asc())
        )
        refunds = result.scalars().all()
        order_ids = {row.order_id for row in refunds}
        orders_by_id = {}
        if order_ids:
            order_result = await session.execute(
                select(OrderModel)
                .options(selectinload(OrderModel.items))
                .where(OrderModel.tenant_id == staff.tenant_id, OrderModel.order_id.in_(order_ids))
            )
            orders_by_id = {order.order_id: order for order in order_result.scalars().all()}

        return [
            {
                "refund_id": row.refund_id,
                "order_id": row.order_id,
                "customer_id": row.customer_id,
                "amount_inr": row.amount_inr,
                "reason": row.reason,
                "state": row.state,
                "created_at": row.request_time.isoformat(),
                "eligibility_snapshot": row.eligibility_snapshot or {},
                "policy_version_applied": row.policy_version_applied,
                "customer_trust_level": (row.eligibility_snapshot or {}).get("customer_trust_level", "unknown"),
                "requested_by": getattr(row, "requested_by", None),
                "order_items": [
                    {
                        "item_id": item.item_id,
                        "title": item.product_name,
                        "quantity": item.quantity,
                        "price_inr": float(item.price),
                        "returnable": bool(item.refund_eligibility_verified and not item.is_digital and not item.is_refunded),
                    }
                    for item in (orders_by_id.get(row.order_id).items if row.order_id in orders_by_id else [])
                ],
                "checks": ([{
                    "name": "Refund eligibility at request time",
                    "passed": (row.eligibility_snapshot or {}).get("eligible") is True,
                    "details": (row.eligibility_snapshot or {}).get("reason") or "Eligibility decision recorded.",
                }] if "eligible" in (row.eligibility_snapshot or {}) else []),
            }
            for row in refunds
        ]


async def _decide(
    refund_id: str,
    decision: str,
    payload: RefundDecision,
    staff: StaffSessionContext,
):
    if decision == "rejected" and not payload.notes.strip():
        raise HTTPException(status_code=422, detail="A staff audit note is required to reject a refund.")

    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        result = await session.execute(
            select(RefundRequest).where(
                RefundRequest.refund_id == refund_id,
                RefundRequest.tenant_id == staff.tenant_id,
                RefundRequest.state == "pending_approval",
            )
        )
        refund = result.scalars().first()
        if not refund:
            raise HTTPException(status_code=409, detail="Refund is no longer pending review.")

        _require_step_up(staff, refund.amount_inr)

        store_result = await _review_store_refund(refund, decision, payload.notes)
        final_state = "processed" if decision == "approved" else "rejected"
        update_result = await session.execute(
            update(RefundRequest)
            .where(
                RefundRequest.refund_id == refund_id,
                RefundRequest.tenant_id == staff.tenant_id,
                RefundRequest.state == "pending_approval",
            )
            .values(
                state=final_state,
                decided_by=staff.staff_id,
                decided_at=now,
                staff_note=payload.notes.strip() or None,
            )
        )
        if update_result.rowcount != 1:
            raise HTTPException(status_code=409, detail="Refund was already decided by another reviewer.")

        session.add(AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:16]}",
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action=f"refund_{final_state}",
            resource_type="refund_request",
            resource_id=refund_id,
            details={"notes": payload.notes.strip()},
            timestamp=now,
        ))

    return {
        "success": True,
        "message": "Refund processed in the store and synchronized." if final_state == "processed" else "Refund rejected in the store and synchronized.",
        "refund_id": refund_id,
        "store_refund_id": store_result.get("refund_id"),
        "amount_inr": store_result.get("amount"),
        "state": final_state,
        "test_mode": store_result.get("test_mode", False),
        "money_moved": store_result.get("money_moved", False),
    }


@integration_router.post("/store-event")
async def sync_store_refund_event(payload: dict, authorization: Optional[str] = Header(default=None)):
    """Machine callback from the storefront after a staff refund decision."""
    expected = os.getenv("APEXSTORE_REFUND_SYNC_SECRET", "")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid integration credential.")
    order_id = str(payload.get("order_id", ""))
    store_status = str(payload.get("status", ""))
    tenant_id = os.getenv("NOVARETAIL_TENANT_ID", "tenant_novaretail")
    if not order_id or store_status not in {"Processed", "Rejected"}:
        raise HTTPException(status_code=422, detail="A valid order ID and final store refund status are required.")
    next_state = "processed" if store_status == "Processed" else "rejected"
    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=tenant_id) as session:
        result = await session.execute(
            select(RefundRequest).where(
                RefundRequest.tenant_id == tenant_id,
                RefundRequest.order_id == order_id,
                RefundRequest.state.in_(["pending_approval", "approved"]),
            )
        )
        rows = result.scalars().all()
        if len(rows) > 1:
            raise HTTPException(status_code=409, detail="Multiple AI refunds match this store order; manual reconciliation is required.")
        if not rows:
            return {"success": True, "synced": False, "reason": "no_open_ai_refund"}
        refund = rows[0]
        refund.state = next_state
        refund.decided_by = "store_admin_sync"
        refund.decided_at = now
        refund.staff_note = str(payload.get("note", ""))[:1000] or f"Synchronized from store refund {payload.get('store_refund_id', '')}."
        refund.leased_until = None
        session.add(AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:16]}", tenant_id=tenant_id,
            actor_id="store_admin_sync", actor_role="system", action=f"refund_{next_state}",
            resource_type="refund_request", resource_id=refund.refund_id,
            details={"store_refund_id": payload.get("store_refund_id"), "amount": payload.get("amount")}, timestamp=now,
        ))
    return {"success": True, "synced": True, "refund_id": refund.refund_id, "state": next_state}


@router.get("/pending")
async def list_pending_refunds(
    refund_id: Optional[str] = None,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    results = await _list_pending(staff)
    return [row for row in results if not refund_id or row["refund_id"] == refund_id]


@router.get("/history")
async def list_refund_history(
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        result = await session.execute(
            select(RefundRequest)
            .where(
                RefundRequest.tenant_id == staff.tenant_id,
                RefundRequest.state != "pending_approval",
            )
            .order_by(RefundRequest.decided_at.desc().nullslast(), RefundRequest.request_time.desc())
            .limit(300)
        )
        return [
            {
                "refund_id": row.refund_id,
                "order_id": row.order_id,
                "customer_id": row.customer_id,
                "amount_inr": float(row.amount_inr),
                "reason": row.reason,
                "state": row.state,
                "created_at": row.request_time.isoformat(),
                "decided_at": row.decided_at.isoformat() if row.decided_at else None,
                "decided_by": row.decided_by,
                "staff_note": row.staff_note,
            }
            for row in result.scalars().all()
        ]


@router.post("/{refund_id}/approve")
async def approve_refund(
    refund_id: str,
    payload: RefundDecision,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    return await _decide(refund_id, "approved", payload, staff)


@router.post("/{refund_id}/reject")
async def reject_refund(
    refund_id: str,
    payload: RefundDecision,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    return await _decide(refund_id, "rejected", payload, staff)


# The older supervisor console uses /desk URLs. Keep them behind the same auth
# and audit policy rather than leaving a second, unauthenticated mutation path.
@legacy_router.get("/desk/refunds/pending")
async def list_legacy_pending_refunds(
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    return await _list_pending(staff)


@legacy_router.post("/desk/refunds/{refund_id}/approve")
async def approve_legacy_refund(
    refund_id: str,
    payload: RefundDecision,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    return await _decide(refund_id, "approved", payload, staff)


@legacy_router.post("/desk/refunds/{refund_id}/reject")
async def reject_legacy_refund(
    refund_id: str,
    payload: RefundDecision,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    return await _decide(refund_id, "rejected", payload, staff)
