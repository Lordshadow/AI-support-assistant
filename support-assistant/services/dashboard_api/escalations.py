"""
Escalations Queue & Human Takeover Console API (Spec 5.2, 16.4).
Provides atomic ticket claiming, resolution workflows, and wait time tracking.
"""

from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update, func

from db.models import Escalation, ConversationSession, AuditEvent
from db.session import get_async_session
from services.dashboard_api.dependencies import (
    get_current_staff, require_roles, StaffSessionContext
)
from services.worker.escalation_guard import escalation_guard

router = APIRouter(prefix="/api/admin/v1/escalations", tags=["escalations"])


class ResolveRequest(BaseModel):
    resolution_note: str = Field(..., min_length=10, description="Mandatory documented resolution notes")


@router.get("")
async def list_escalations(
    esc_id: Optional[str] = Query(None),
    state: Optional[str] = Query(None, description="Filter by state: open, assigned, resolved"),
    priority: Optional[str] = Query(None, description="Filter by priority: low, medium, high, urgent"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    """List escalation queue tickets with calculated wait times."""
    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        stmt = select(Escalation).where(Escalation.tenant_id == staff.tenant_id)
        if esc_id:
            stmt = stmt.where(Escalation.esc_id == esc_id)
        if state:
            stmt = stmt.where(Escalation.state == state)
        if priority:
            stmt = stmt.where(Escalation.priority == priority)

        count_stmt = select(func.count(Escalation.esc_id)).where(Escalation.tenant_id == staff.tenant_id)
        if esc_id:
            count_stmt = count_stmt.where(Escalation.esc_id == esc_id)
        if state:
            count_stmt = count_stmt.where(Escalation.state == state)
        if priority:
            count_stmt = count_stmt.where(Escalation.priority == priority)
        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(Escalation.created_at.desc()).offset(offset).limit(limit)
        tickets = (await session.execute(stmt)).scalars().all()

        results = []
        for t in tickets:
            created_ts = t.created_at if t.created_at.tzinfo else t.created_at.replace(tzinfo=timezone.utc)
            wait_min = round((now - created_ts).total_seconds() / 60.0, 1) if t.state != "resolved" else 0.0

            results.append({
                "esc_id": t.esc_id,
                "conv_id": t.conv_id,
                "reason": t.reason,
                "summary": t.summary,
                "priority": t.priority,
                "state": t.state,
                "assigned_to": t.assigned_to,
                "wait_minutes": wait_min,
                "created_at": created_ts.isoformat(),
                "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
                "resolution_note": t.resolution_note,
            })

        return {"escalations": results, "count": len(results), "total": total}


@router.post("/{esc_id}/claim")
async def claim_escalation(
    esc_id: str,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    """
    Atomic ticket claim:
    UPDATE escalations SET state='assigned', assigned_to=:staff WHERE esc_id=:id AND state='open';
    If rowcount != 1, raises 409 Conflict ("Already claimed").
    """
    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        # Atomic conditional update
        stmt = (
            update(Escalation)
            .where(
                Escalation.tenant_id == staff.tenant_id,
                Escalation.esc_id == esc_id,
                Escalation.state == "open"
            )
            .values(
                state="assigned",
                assigned_to=staff.staff_id
            )
        )
        res = await session.execute(stmt)
        if res.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Conflict: Escalation ticket '{esc_id}' is no longer open or was already claimed by another executive."
            )

        # Update conversation session handoff state
        esc = await session.get(Escalation, esc_id)
        if esc and esc.conv_id:
            conv = await session.get(ConversationSession, esc.conv_id)
            if conv:
                conv.handoff_state = "assigned"

        # Audit event in same transaction
        audit = AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action="claim_escalation",
            resource_type="escalation",
            resource_id=esc_id,
            details={"assigned_to": staff.staff_id},
            timestamp=now
        )
        session.add(audit)

        return {
            "status": "assigned",
            "esc_id": esc_id,
            "assigned_to": staff.staff_id,
            "timestamp": now.isoformat()
        }


@router.post("/{esc_id}/resolve")
async def resolve_escalation(
    esc_id: str,
    req: ResolveRequest,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
):
    """Resolves an escalation with mandatory documentation notes (>= 10 characters)."""
    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        esc = await session.get(Escalation, esc_id)
        if not esc or esc.tenant_id != staff.tenant_id:
            raise HTTPException(status_code=404, detail="Escalation ticket not found.")

        if esc.state == "resolved":
            return {"status": "already_resolved", "esc_id": esc_id}

        esc.state = "resolved"
        esc.resolved_at = now
        esc.resolution_note = req.resolution_note.strip()

        # Update conversation session
        if esc.conv_id:
            conv = await session.get(ConversationSession, esc.conv_id)
            if conv:
                conv.handoff_state = "resolved"
            escalation_guard.set_mock_silenced(esc.conv_id, False)

        # Audit record
        audit = AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action="resolve_escalation",
            resource_type="escalation",
            resource_id=esc_id,
            details={"note": req.resolution_note.strip(), "resolved_by": staff.staff_id},
            timestamp=now
        )
        session.add(audit)

        return {
            "status": "resolved",
            "esc_id": esc_id,
            "resolved_at": now.isoformat(),
            "resolution_note": req.resolution_note.strip()
        }
