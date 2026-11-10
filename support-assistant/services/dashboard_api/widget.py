"""
Widget & Embed Code Integration API for Master Control Dashboard.
Complies with Specification Section 16.1 & 16.2.
"""

import os
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from db.models import Tenant
from db.session import get_async_session

from services.dashboard_api.dependencies import (
    require_roles, StaffSessionContext
)

router = APIRouter(prefix="/api/admin/v1/widget", tags=["widget"])

DEFAULT_WIDGET_CONFIG = {"name": "NovaRetail Support", "greeting": "Hi! How can I help you today?", "primaryColor": "#0284c7", "theme": "light", "launcherSide": "right", "quickPrompts": ["Track my order", "Product questions"], "autoOpen": False}


class WidgetSettings(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    greeting: str = Field(min_length=1, max_length=180)
    primaryColor: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    theme: str = Field(pattern=r"^(light|dark)$")
    launcherSide: str = Field(pattern=r"^(left|right)$")
    quickPrompts: List[str] = Field(default_factory=list, max_length=3)
    autoOpen: bool = False

    @field_validator("quickPrompts")
    @classmethod
    def clean_prompts(cls, prompts):
        prompts = [str(prompt).strip()[:80] for prompt in prompts if str(prompt).strip()]
        if len(prompts) > 3:
            raise ValueError("At most three quick prompts are allowed.")
        return prompts


@router.get("/config")
def get_widget_config(
    request: Request,
    staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin")),
) -> Dict[str, Any]:
    """
    Returns embed configuration, origin allowlist status, and integration parameters
    for the current staff member's active tenant.
    """
    raw_origins = os.getenv("WIDGET_ALLOWED_ORIGINS")
    if raw_origins:
        configured_origins = [v.strip().rstrip("/") for v in raw_origins.split(",") if v.strip()]
    else:
        # Default security allowlist
        configured_origins = ["https://shop.novaretail.com", "http://localhost:3000"]

    # Base URL inference
    host_header = request.headers.get("host")
    scheme = "https" if request.url.is_secure or request.headers.get("x-forwarded-proto") == "https" else "http"
    inferred_base = f"{scheme}://{host_header}" if host_header else "http://localhost:8000"

    tenant_id = staff.tenant_id or "tenant_novaretail"

    return {
        "tenant_id": tenant_id,
        "widget_config": DEFAULT_WIDGET_CONFIG,
        "script_url": f"{inferred_base}/widget/v1/widget.js",
        "script_path": "/widget/v1/widget.js",
        "demo_url": f"{inferred_base}/widget/index.html",
        "api_base": inferred_base,
        "allowed_origins": configured_origins,
        "security_spec": {
            "shadow_dom": "Open Shadow DOM (mode: 'open') ensures complete CSS isolation from host styles",
            "xss_protection": "Zero innerHTML rendering; messages rendered strictly via textContent",
            "origin_guard": "Spec 16.2 server-side validation against WIDGET_ALLOWED_ORIGINS (fails closed)",
            "token_refresh": "Dynamic runtime token retrieval via data-get-token callback",
        },
        "default_snippet": f'<script src="{inferred_base}/widget/v1/widget.js" data-tenant="{tenant_id}" data-api-base="{inferred_base}" defer></script>',
    }


@router.get("/settings")
async def read_widget_settings(staff: StaffSessionContext = Depends(require_roles("executive", "manager", "admin"))):
    async with get_async_session(staff.tenant_id) as session:
        tenant = await session.get(Tenant, staff.tenant_id)
        return tenant.widget_config if tenant and tenant.widget_config else DEFAULT_WIDGET_CONFIG


@router.put("/settings")
async def save_widget_settings(payload: WidgetSettings, staff: StaffSessionContext = Depends(require_roles("manager", "admin"))):
    async with get_async_session(staff.tenant_id) as session:
        tenant = await session.get(Tenant, staff.tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")
        tenant.widget_config = payload.model_dump()
        return tenant.widget_config
