"""
Conversations & Spec 14.1 Trace Viewer API (Requirement R5, Spec 14.1, 16.4).
Provides masked transcripts, full trace views, and audited Manager-only PII unmasking.
"""

from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from db.models import (
    ConversationSession, ConversationTurn, TurnRaw, AuditEvent, SpendLedger
)
from db.session import get_async_session
from services.dashboard_api.dependencies import (
    get_current_staff, require_roles, require_step_up, StaffSessionContext
)

router = APIRouter(prefix="/api/admin/v1/conversations", tags=["conversations"])


class UnmaskRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Documented compliance or escalation rationale for PII unmasking")


@router.get("")
async def list_conversations(
    conv_id: Optional[str] = None,
    channel: Optional[str] = None,
    handoff_state: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    staff: StaffSessionContext = Depends(require_roles("executive", "manager")),
):
    """List customer conversation sessions with metadata (Executives & Managers only)."""
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        stmt = select(ConversationSession).where(ConversationSession.tenant_id == staff.tenant_id)
        if conv_id:
            stmt = stmt.where(ConversationSession.conv_id == conv_id)
        if channel:
            stmt = stmt.where(ConversationSession.channel == channel)
        if handoff_state:
            stmt = stmt.where(ConversationSession.handoff_state == handoff_state)

        count_stmt = select(func.count(ConversationSession.conv_id)).where(ConversationSession.tenant_id == staff.tenant_id)
        if conv_id:
            count_stmt = count_stmt.where(ConversationSession.conv_id == conv_id)
        if channel:
            count_stmt = count_stmt.where(ConversationSession.channel == channel)
        if handoff_state:
            count_stmt = count_stmt.where(ConversationSession.handoff_state == handoff_state)
        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(ConversationSession.last_user_message_at.desc()).offset(offset).limit(limit)
        convs = (await session.execute(stmt)).scalars().all()

        results = []
        for c in convs:
            # Count turns
            stmt_turns = (
                select(func.count(ConversationTurn.turn_id))
                .where(ConversationTurn.conv_id == c.conv_id)
            )
            turn_count = (await session.execute(stmt_turns)).scalar() or 0
            results.append({
                "conv_id": c.conv_id,
                "customer_id": c.customer_id,
                "channel": c.channel,
                "handoff_state": c.handoff_state,
                "last_activity": c.last_user_message_at.isoformat(),
                "turn_count": turn_count,
            })

        return {"conversations": results, "count": len(results), "total": total}


@router.get("/{conv_id}")
async def get_conversation_transcript(
    conv_id: str,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager")),
):
    """Retrieve DPDP-masked conversation transcript (Audited Read)."""
    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        conv = await session.get(ConversationSession, conv_id)
        if not conv or conv.tenant_id != staff.tenant_id:
            raise HTTPException(status_code=404, detail="Conversation session not found.")

        # Query turns
        stmt = (
            select(ConversationTurn)
            .where(ConversationTurn.conv_id == conv_id)
            .order_by(ConversationTurn.step_index.asc())
        )
        turns = (await session.execute(stmt)).scalars().all()

        # Audit read event
        audit = AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action="view_conversation_transcript",
            resource_type="conversation_session",
            resource_id=conv_id,
            details={"step_count": len(turns)},
            timestamp=now
        )
        session.add(audit)

        dialogue = [
            {
                "turn_id": t.turn_id,
                "step_index": t.step_index,
                "user_masked": t.user_input_masked,
                "assistant_masked": t.assistant_response_masked,
                "intent": t.intent,
                "timestamp": t.created_at.isoformat(),
            }
            for t in turns
        ]

        return {
            "conv_id": conv.conv_id,
            "customer_id": conv.customer_id,
            "channel": conv.channel,
            "handoff_state": conv.handoff_state,
            "turns": dialogue,
        }


@router.get("/{conv_id}/turns/{turn_id}/trace")
async def get_turn_trace(
    conv_id: str,
    turn_id: str,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager")),
):
    """Retrieve full Spec 14.1 trace columns for a single turn (Audited Read)."""
    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        stmt = select(ConversationTurn).where(
            ConversationTurn.conv_id == conv_id,
            ConversationTurn.turn_id == turn_id,
            ConversationTurn.tenant_id == staff.tenant_id
        )
        turn = (await session.execute(stmt)).scalars().first()
        if not turn:
            raise HTTPException(status_code=404, detail="Turn record not found.")

        spend_stmt = (
            select(SpendLedger)
            .where(SpendLedger.tenant_id == staff.tenant_id, SpendLedger.turn_id == turn_id)
            .order_by(SpendLedger.created_at.desc())
            .limit(1)
        )
        spend = (await session.execute(spend_stmt)).scalars().first()

        # Audit trace read
        audit = AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action="view_turn_trace",
            resource_type="conversation_turn",
            resource_id=turn_id,
            details={"intent": turn.intent, "latency_ms": turn.latency_ms},
            timestamp=now
        )
        session.add(audit)

        return {
            "turn_id": turn.turn_id,
            "conv_id": turn.conv_id,
            "step_index": turn.step_index,
            "intent": turn.intent,
            "latency_ms": turn.latency_ms,
            "tokens_prompt": turn.tokens_prompt,
            "tokens_completion": turn.tokens_completion,
            "model_name": spend.model if spend else None,
            "cost_inr": spend.cost_inr if spend else None,
            "tool_calls": turn.tool_calls_json,
            "grounding_score": turn.grounding_score,
            "user_masked": turn.user_input_masked,
            "assistant_masked": turn.assistant_response_masked,
            "created_at": turn.created_at.isoformat(),
        }


@router.post("/{conv_id}/unmask")
async def unmask_conversation_pii(
    conv_id: str,
    req: UnmaskRequest,
    staff: StaffSessionContext = Depends(require_roles("manager")),
    _step: StaffSessionContext = Depends(require_step_up),
):
    """
    Manager-only PII Unmasking Workflow (Requires Step-Up Authentication).
    Extracts raw user text from turn_raw and logs an immutable audit event with rationale.
    """
    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        stmt = (
            select(TurnRaw, ConversationTurn.step_index)
            .join(ConversationTurn, TurnRaw.turn_id == ConversationTurn.turn_id)
            .where(
                TurnRaw.tenant_id == staff.tenant_id,
                ConversationTurn.conv_id == conv_id
            )
            .order_by(ConversationTurn.step_index.asc())
        )
        rows = (await session.execute(stmt)).all()
        if not rows:
            raise HTTPException(status_code=404, detail="Raw turn data not found or conversation does not exist.")

        # Audit unmask event with mandatory reason
        audit = AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role="manager",
            action="unmask_pii_transcript",
            resource_type="conversation_session",
            resource_id=conv_id,
            details={"reason": req.reason, "turns_unmasked": len(rows)},
            timestamp=now
        )
        session.add(audit)

        unmasked_turns = [
            {
                "turn_id": raw.turn_id,
                "step_index": step_idx,
                "user_raw": raw.user_input_raw,
                "assistant_raw": raw.assistant_response_raw,
                "contact_details": raw.contact_details,
            }
            for raw, step_idx in rows
        ]

        return {
            "conv_id": conv_id,
            "unmasked_by": staff.staff_id,
            "reason": req.reason,
            "timestamp": now.isoformat(),
            "unmasked_turns": unmasked_turns,
        }
