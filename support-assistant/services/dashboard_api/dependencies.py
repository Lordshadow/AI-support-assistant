"""
FastAPI Dependencies for Staff Authentication, CSRF Validation, RBAC, and Step-Up.
Complies with Specification Section 15.1.8.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Optional, List, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, text

from db.models import StaffSession, StaffUser, StaffTenantMembership
from db.session import get_async_session
from services.dashboard_api.auth import is_session_stepped_up


@dataclass(frozen=True)
class StaffSessionContext:
    staff_id: str
    email: str
    full_name: str
    tenant_id: str
    role: str  # 'executive', 'manager', 'admin'
    session_id: str
    is_stepped_up: bool


async def get_current_staff(request: Request) -> StaffSessionContext:
    """
    Extracts session ID from HttpOnly cookie (or Bearer auth header for testing).
    Enforces double-submit CSRF verification on state-mutating HTTP methods.
    """
    # 1. Extract session token
    session_id = request.cookies.get("session_id")
    if not session_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            session_id = auth_header[7:].strip()

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to the Master Control Dashboard."
        )

    now = datetime.now(timezone.utc)

    # 2. Query session row
    async with get_async_session() as session:
        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT set_config('app.session_id', :session_id, true)"),
                {"session_id": session_id},
            )
        stmt = select(StaffSession).where(
            StaffSession.session_id == session_id,
            StaffSession.revoked_at == None,
            StaffSession.expires_at > now,
        )
        staff_sess = (await session.execute(stmt)).scalars().first()
        if not staff_sess:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session has expired or was revoked. Please log in again."
            )

        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": staff_sess.active_tenant_id},
            )

        # 3. Double-Submit CSRF check for state mutations
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            csrf_header = request.headers.get("X-CSRF-Token")
            if not csrf_header:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Missing X-CSRF-Token header for state-mutating request."
                )
            computed_hash = hashlib.sha256(csrf_header.encode("utf-8")).hexdigest()
            if computed_hash != staff_sess.csrf_hash:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid CSRF token."
                )

        # 4. Fetch user details and active role from memberships
        user = await session.get(StaffUser, staff_sess.staff_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account associated with this session no longer exists."
            )

        stmt_role = select(StaffTenantMembership).where(
            StaffTenantMembership.staff_id == staff_sess.staff_id,
            StaffTenantMembership.tenant_id == staff_sess.active_tenant_id,
        )
        membership = (await session.execute(stmt_role)).scalars().first()
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Staff account is not a member of tenant '{staff_sess.active_tenant_id}'."
            )

        stepped_up = is_session_stepped_up(session_id)

        return StaffSessionContext(
            staff_id=user.staff_id,
            email=user.email,
            full_name=user.full_name,
            tenant_id=staff_sess.active_tenant_id,
            role=membership.role,
            session_id=session_id,
            is_stepped_up=stepped_up,
        )


def require_roles(*allowed_roles: str) -> Callable:
    """Dependency factory checking that staff role is in allowed_roles."""
    async def role_checker(staff: StaffSessionContext = Depends(get_current_staff)) -> StaffSessionContext:
        if staff.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Action requires one of roles: {list(allowed_roles)}. Your role is '{staff.role}'."
            )
        return staff
    return role_checker


async def require_step_up(staff: StaffSessionContext = Depends(get_current_staff)) -> StaffSessionContext:
    """Dependency verifying that the session has valid step-up authorization (< 5 minutes)."""
    if not staff.is_stepped_up:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Step-up authentication required for this high-privilege action.",
                "code": "STEP_UP_REQUIRED"
            }
        )
    return staff
