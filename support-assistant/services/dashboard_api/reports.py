"""
Dashboard Reports API (Requirement R4, Spec 6.2, 11.1).
Aggregates live token spend against daily/monthly caps and deflection metrics.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func

from db.models import SpendLedger, ConversationSession, ConversationTurn, Tenant
from db.session import get_async_session
from services.dashboard_api.dependencies import (
    get_current_staff, require_roles, StaffSessionContext
)

router = APIRouter(prefix="/api/admin/v1/reports", tags=["reports"])


@router.get("/spend")
async def get_spend_report(
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """Token usage and INR cost report with daily (₹2,500) and monthly (₹50,000) budget meters."""
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    async with get_async_session(tenant_id=staff.tenant_id) as session:
        # Get tenant caps
        tenant = await session.get(Tenant, staff.tenant_id)
        daily_cap = tenant.daily_spend_cap_inr if tenant else 2500
        monthly_cap = tenant.monthly_spend_cap_inr if tenant else 50000

        # Query today's spend
        stmt_today = (
            select(
                func.coalesce(func.sum(SpendLedger.cost_inr), 0.0),
                func.coalesce(func.sum(SpendLedger.prompt_tokens), 0),
                func.coalesce(func.sum(SpendLedger.completion_tokens), 0)
            )
            .where(
                SpendLedger.tenant_id == staff.tenant_id,
                SpendLedger.created_at >= today_start
            )
        )
        today_cost, today_prompt, today_comp = (await session.execute(stmt_today)).one()

        # Query this month's spend
        stmt_month = (
            select(
                func.coalesce(func.sum(SpendLedger.cost_inr), 0.0),
                func.coalesce(func.sum(SpendLedger.prompt_tokens), 0),
                func.coalesce(func.sum(SpendLedger.completion_tokens), 0)
            )
            .where(
                SpendLedger.tenant_id == staff.tenant_id,
                SpendLedger.created_at >= month_start
            )
        )
        month_cost, month_prompt, month_comp = (await session.execute(stmt_month)).one()

        # Model breakdown
        stmt_models = (
            select(
                SpendLedger.model,
                func.count(SpendLedger.id),
                func.sum(SpendLedger.prompt_tokens),
                func.sum(SpendLedger.completion_tokens),
                func.sum(SpendLedger.cost_inr)
            )
            .where(
                SpendLedger.tenant_id == staff.tenant_id,
                SpendLedger.created_at >= month_start
            )
            .group_by(SpendLedger.model)
        )
        model_rows = (await session.execute(stmt_models)).all()

        models_breakdown = [
            {
                "model": row[0],
                "calls": row[1],
                "prompt_tokens": row[2] or 0,
                "completion_tokens": row[3] or 0,
                "cost_inr": round(row[4] or 0.0, 4),
            }
            for row in model_rows
        ]

        daily_utilization = round((today_cost / daily_cap) * 100, 2) if daily_cap > 0 else 0.0
        monthly_utilization = round((month_cost / monthly_cap) * 100, 2) if monthly_cap > 0 else 0.0

        return {
            "tenant_id": staff.tenant_id,
            "daily": {
                "spent_inr": round(today_cost, 2),
                "cap_inr": daily_cap,
                "utilization_pct": daily_utilization,
                "tokens": today_prompt + today_comp,
                "status": "capped" if today_cost >= daily_cap else "normal"
            },
            "monthly": {
                "spent_inr": round(month_cost, 2),
                "cap_inr": monthly_cap,
                "utilization_pct": monthly_utilization,
                "tokens": month_prompt + month_comp,
                "status": "capped" if month_cost >= (monthly_cap * 0.95) else "normal"
            },
            "models": models_breakdown
        }


@router.get("/metrics")
async def get_performance_metrics(
    days: int = Query(30, ge=1, le=90),
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
):
    """Customer experience performance metrics: deflection rate, latency, and average cost per turn."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    async with get_async_session(tenant_id=staff.tenant_id) as session:
        # 1. Total conversations & Deflection
        stmt_convs = (
            select(ConversationSession.handoff_state)
            .where(
                ConversationSession.tenant_id == staff.tenant_id,
                ConversationSession.created_at >= since
            )
        )
        conv_states = (await session.execute(stmt_convs)).scalars().all()
        total_convs = len(conv_states)
        deflected = sum(1 for s in conv_states if s in ("none", "resolved"))
        deflection_rate = round((deflected / total_convs) * 100, 1) if total_convs > 0 else 100.0

        # 2. Latencies from turns
        stmt_latencies = (
            select(ConversationTurn.latency_ms)
            .where(
                ConversationTurn.tenant_id == staff.tenant_id,
                ConversationTurn.created_at >= since
            )
            .order_by(ConversationTurn.latency_ms.asc())
        )
        latencies = (await session.execute(stmt_latencies)).scalars().all()
        n_turns = len(latencies)

        avg_latency = round(sum(latencies) / n_turns, 1) if n_turns > 0 else 0.0
        p50 = latencies[int(n_turns * 0.50)] if n_turns > 0 else 0
        p95 = latencies[int(n_turns * 0.95)] if n_turns > 0 else 0

        # 3. Cost calculation
        stmt_cost = (
            select(func.coalesce(func.sum(SpendLedger.cost_inr), 0.0))
            .where(
                SpendLedger.tenant_id == staff.tenant_id,
                SpendLedger.created_at >= since
            )
        )
        total_cost = (await session.execute(stmt_cost)).scalar() or 0.0
        cost_per_conv = round(total_cost / total_convs, 2) if total_convs > 0 else 0.0

        return {
            "tenant_id": staff.tenant_id,
            "period_days": days,
            "conversations": {
                "total": total_convs,
                "deflected": deflected,
                "deflection_rate_pct": deflection_rate,
                "escalated": total_convs - deflected,
            },
            "latency_ms": {
                "average": avg_latency,
                "p50": p50,
                "p95": p95,
            },
            "financials": {
                "total_spend_inr": round(total_cost, 2),
                "cost_per_conversation_inr": cost_per_conv,
            }
        }
