"""Authenticated refund review API used by the staff dashboard."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from db.models import AuditEvent, RefundRequest
from db.session import get_async_session
from services.dashboard_api.dependencies import StaffSessionContext, require_roles

router = APIRouter(prefix="/api/admin/v1/refunds", tags=["refunds"])
legacy_router = APIRouter(tags=["legacy-refunds"])


class RefundDecision(BaseModel):
    notes: str = ""


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
        return [
            {
                "refund_id": row.refund_id,
                "order_id": row.order_id,
                "customer_id": row.customer_id,
                "amount_inr": row.amount_inr,
                "reason": row.reason,
                "state": row.state,
                "created_at": row.request_time.isoformat(),
            }
            for row in result.scalars().all()
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

        # Spec 15.1.8 [ASSUMPTION]: Staff cannot approve a refund they requested themselves
        if refund.requested_by and refund.requested_by == staff.staff_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff cannot approve a refund they requested themselves."
            )

        _require_step_up(staff, refund.amount_inr)

        update_result = await session.execute(
            update(RefundRequest)
            .where(
                RefundRequest.refund_id == refund_id,
                RefundRequest.tenant_id == staff.tenant_id,
                RefundRequest.state == "pending_approval",
            )
            .values(
                state=decision,
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
            action=f"refund_{decision}",
            resource_type="refund_request",
            resource_id=refund_id,
            details={"notes": payload.notes.strip()},
            timestamp=now,
        ))

    return {"success": True, "message": f"Refund {decision}.", "refund_id": refund_id, "state": decision}


@router.get("/pending")
async def list_pending_refunds(
    refund_id: Optional[str] = None,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    results = await _list_pending(staff)
    return [row for row in results if not refund_id or row["refund_id"] == refund_id]


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
