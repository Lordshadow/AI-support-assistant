"""
Tenant Governance & Dashboard Settings API (Spec 16.4 Screen 6).
Provides threshold controls, working hours, spend caps, and diff-audited mutations.
"""

from datetime import datetime, timezone
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from db.models import Tenant, AuditEvent
from db.session import get_async_session
from services.dashboard_api.dependencies import (
    StaffSessionContext, require_roles
)

router = APIRouter(prefix="/api/admin/v1/settings", tags=["settings"])


class TenantSettingsPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    auto_refund_limit_inr: int = Field(default=2000, ge=0, le=50000)
    daily_spend_cap_inr: int = Field(default=2500, ge=100, le=500000)
    monthly_spend_cap_inr: int = Field(default=50000, ge=1000, le=5000000)
    working_hours_start: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    working_hours_end: str = Field(default="20:00", pattern=r"^\d{2}:\d{2}$")
    timezone: str = Field(default="Asia/Kolkata")
    supported_languages: List[str] = Field(default_factory=lambda: ["en", "hi", "ta", "te"])
    confidence_threshold: float = Field(default=0.85, ge=0.5, le=1.0)
    grounding_threshold: float = Field(default=0.90, ge=0.5, le=1.0)
    refund_turnaround_hours: int = Field(default=24, ge=1, le=168)


@router.get("")
async def get_tenant_settings(
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
) -> Dict[str, Any]:
    """Retrieve current workspace threshold and operational settings."""
    async with get_async_session(staff.tenant_id) as session:
        tenant = await session.get(Tenant, staff.tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant workspace not found.")

        cfg = tenant.widget_config or {}
        return {
            "tenant_id": tenant.tenant_id,
            "name": tenant.name,
            "auto_refund_limit_inr": cfg.get("auto_refund_limit_inr", 2000),
            "daily_spend_cap_inr": tenant.daily_spend_cap_inr or 2500,
            "monthly_spend_cap_inr": tenant.monthly_spend_cap_inr or 50000,
            "working_hours_start": tenant.working_hours_start or "09:00",
            "working_hours_end": tenant.working_hours_end or "20:00",
            "timezone": tenant.timezone or "Asia/Kolkata",
            "supported_languages": cfg.get("supported_languages", ["en", "hi", "ta", "te"]),
            "confidence_threshold": cfg.get("confidence_threshold", 0.85),
            "grounding_threshold": cfg.get("grounding_threshold", 0.90),
            "refund_turnaround_hours": tenant.refund_turnaround_hours or 24,
        }


@router.put("")
async def update_tenant_settings(
    payload: TenantSettingsPayload,
    staff: StaffSessionContext = Depends(require_roles("manager", "admin")),
) -> Dict[str, Any]:
    """
    Update workspace thresholds and configuration.
    Computes exact field diff and writes immutable record to audit_events.
    """
    now = datetime.now(timezone.utc)
    async with get_async_session(staff.tenant_id) as session:
        tenant = await session.get(Tenant, staff.tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant workspace not found.")

        # Capture old values
        old_cfg = tenant.widget_config or {}
        old_values = {
            "name": tenant.name,
            "auto_refund_limit_inr": old_cfg.get("auto_refund_limit_inr", 2000),
            "daily_spend_cap_inr": tenant.daily_spend_cap_inr,
            "monthly_spend_cap_inr": tenant.monthly_spend_cap_inr,
            "working_hours_start": tenant.working_hours_start,
            "working_hours_end": tenant.working_hours_end,
            "timezone": tenant.timezone,
            "supported_languages": old_cfg.get("supported_languages", ["en", "hi", "ta", "te"]),
            "confidence_threshold": old_cfg.get("confidence_threshold", 0.85),
            "grounding_threshold": old_cfg.get("grounding_threshold", 0.90),
            "refund_turnaround_hours": tenant.refund_turnaround_hours,
        }

        new_dict = payload.model_dump()
        diff = {}
        for key, val in new_dict.items():
            if old_values.get(key) != val:
                diff[key] = {"old": old_values.get(key), "new": val}

        # Apply updates
        tenant.name = payload.name
        tenant.daily_spend_cap_inr = payload.daily_spend_cap_inr
        tenant.monthly_spend_cap_inr = payload.monthly_spend_cap_inr
        tenant.working_hours_start = payload.working_hours_start
        tenant.working_hours_end = payload.working_hours_end
        tenant.timezone = payload.timezone
        tenant.refund_turnaround_hours = payload.refund_turnaround_hours

        # Update JSON config items
        updated_cfg = dict(old_cfg)
        updated_cfg["auto_refund_limit_inr"] = payload.auto_refund_limit_inr
        updated_cfg["supported_languages"] = payload.supported_languages
        updated_cfg["confidence_threshold"] = payload.confidence_threshold
        updated_cfg["grounding_threshold"] = payload.grounding_threshold
        tenant.widget_config = updated_cfg

        # Record immutable audit event
        audit = AuditEvent(
            event_id=f"AUD-{uuid.uuid4().hex[:12].upper()}",
            tenant_id=staff.tenant_id,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action="update_tenant_settings",
            resource_type="tenant_settings",
            resource_id=tenant.tenant_id,
            details={"diff": diff, "field_count": len(diff)},
            timestamp=now,
        )
        session.add(audit)

        return {
            "success": True,
            "message": f"Settings successfully updated ({len(diff)} fields changed).",
            "diff": diff,
            "settings": {
                "tenant_id": tenant.tenant_id,
                **new_dict,
            },
        }
