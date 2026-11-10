"""
Staff Authentication & Identity Service (Spec 15.1.8).
Argon2id hashing, RFC 6238 TOTP MFA, opaque server-side sessions, and double-submit CSRF.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import re
import os
import secrets
from typing import Optional, Dict, Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import StaffUser, StaffTenantMembership, StaffSession, Tenant, AuditEvent
from db.session import get_async_session

ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16
)

router = APIRouter(prefix="/api/admin/v1/auth", tags=["auth"])

# In-memory ticket cache for MFA step (TTL: 5 minutes)
_mfa_tickets: Dict[str, Dict[str, Any]] = {}
# In-memory step-up status tracker: session_id -> datetime (valid for 5 minutes)
_step_up_tracker: Dict[str, datetime] = {}


async def _current_staff(request: Request):
    # Import lazily because dependencies imports the step-up tracker from this module.
    from services.dashboard_api.dependencies import get_current_staff
    return await get_current_staff(request)


async def _admin_staff(request: Request):
    from fastapi import HTTPException, status
    staff = await _current_staff(request)
    if staff.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required.")
    return staff


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return ph.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, issuer: str = "NovaRetail Support Desk") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code.strip(), valid_window=1)


def is_session_stepped_up(session_id: str) -> bool:
    valid_until = _step_up_tracker.get(session_id)
    if not valid_until:
        return False
    return datetime.now(timezone.utc) < valid_until


def mark_session_stepped_up(session_id: str, duration_minutes: int = 5):
    _step_up_tracker[session_id] = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)


# Pydantic Schemas
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: Optional[str] = None


class MFAVerifyRequest(BaseModel):
    mfa_ticket: str
    code: str


class StepUpRequest(BaseModel):
    password: Optional[str] = None
    totp_code: Optional[str] = None


class SwitchTenantRequest(BaseModel):
    tenant_id: str


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    now = datetime.now(timezone.utc)
    email_clean = req.email.strip().lower()
    login_error = None
    login_result = None

    async with get_async_session() as session:
        stmt = select(StaffUser).where(StaffUser.email == email_clean)
        user = (await session.execute(stmt)).scalars().first()

        # Constant-time mitigation against timing attacks if user not found
        dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$5W2O/G/m0kZ7P5yJ3M342mK6"
        target_hash = user.password_hash if user else dummy_hash

        if user and user.locked_until and user.locked_until > now:
            login_error = HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is temporarily locked due to failed attempts. Please try again later."
            )
        elif not verify_password(target_hash, req.password) or not user:
            if user:
                user.failed_attempts += 1
                if user.failed_attempts >= 5:
                    user.locked_until = now + timedelta(minutes=15)
            login_error = HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
        else:
            # Successful password verification: reset failed attempts.
            user.failed_attempts = 0
            user.locked_until = None

            # If user has MFA enrolled, issue short-lived MFA ticket.
            if user.mfa_secret:
                ticket = f"mfa_{secrets.token_urlsafe(32)}"
                _mfa_tickets[ticket] = {
                    "staff_id": user.staff_id,
                    "email": user.email,
                    "preferred_tenant": req.tenant_id or os.getenv("NOVARETAIL_TENANT_ID", "demo-shop").strip(),
                    "expires_at": now + timedelta(minutes=5),
                }
                login_result = {
                    "status": "mfa_required",
                    "mfa_ticket": ticket,
                    "message": "Enter your 6-digit authenticator code."
                }
            else:
                # The surrounding session context commits after this helper returns.
                login_result = await _create_staff_session(
                    user.staff_id,
                    req.tenant_id or os.getenv("NOVARETAIL_TENANT_ID", "demo-shop").strip(),
                    response,
                    session,
                )

    if login_error:
        raise login_error
    return login_result


@router.post("/mfa/verify")
async def verify_mfa(req: MFAVerifyRequest, response: Response):
    now = datetime.now(timezone.utc)
    ticket_data = _mfa_tickets.get(req.mfa_ticket)

    if not ticket_data or ticket_data["expires_at"] < now:
        if req.mfa_ticket in _mfa_tickets:
            del _mfa_tickets[req.mfa_ticket]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA ticket expired or invalid. Please log in again."
        )

    staff_id = ticket_data["staff_id"]
    preferred_tenant = ticket_data.get("preferred_tenant")

    async with get_async_session() as session:
        user = await session.get(StaffUser, staff_id)
        if not user or not user.mfa_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA state.")

        if not verify_totp(user.mfa_secret, req.code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authenticator code.")

        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT set_config('app.staff_id', :staff_id, true)"),
                {"staff_id": staff_id},
            )

        # Delete consumed ticket
        del _mfa_tickets[req.mfa_ticket]
        return await _create_staff_session(staff_id, preferred_tenant, response, session)


async def _create_staff_session(
    staff_id: str,
    preferred_tenant: Optional[str],
    response: Response,
    session: AsyncSession
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)

    if session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT set_config('app.staff_id', :staff_id, true)"),
            {"staff_id": staff_id},
        )

    # 1. Resolve tenant membership
    stmt = (
        select(StaffTenantMembership, Tenant.name)
        .join(Tenant, StaffTenantMembership.tenant_id == Tenant.tenant_id)
        .where(StaffTenantMembership.staff_id == staff_id)
    )
    memberships = (await session.execute(stmt)).all()
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to any active organization/tenant."
        )

    # Pick preferred or first available tenant membership
    active_membership = None
    if preferred_tenant:
        for m, tname in memberships:
            if m.tenant_id == preferred_tenant:
                active_membership = (m, tname)
                break
    if not active_membership:
        active_membership = memberships[0]

    membership_obj, tenant_name = active_membership

    if session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": membership_obj.tenant_id},
        )

    # 2. Generate opaque session ID and CSRF token
    session_id = f"sess_{secrets.token_urlsafe(32)}"
    csrf_token = secrets.token_urlsafe(32)
    csrf_hash = hashlib.sha256(csrf_token.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(hours=8)

    db_sess = StaffSession(
        session_id=session_id,
        staff_id=staff_id,
        tenant_id=membership_obj.tenant_id,
        active_tenant_id=membership_obj.tenant_id,
        created_at=now,
        expires_at=expires_at,
        csrf_hash=csrf_hash,
    )
    session.add(db_sess)

    # Record login audit event
    audit = AuditEvent(
        event_id=f"AUD-{secrets.token_hex(8)}",
        tenant_id=membership_obj.tenant_id,
        actor_id=staff_id,
        actor_role=membership_obj.role,
        action="staff_login",
        resource_type="auth_session",
        resource_id=session_id,
        details={"tenant_id": membership_obj.tenant_id, "role": membership_obj.role},
        timestamp=now,
    )
    session.add(audit)
    # 3. Set HttpOnly, SameSite=Strict cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="strict",
        secure=False,  # Set to True when HTTPS is enabled
        max_age=8 * 3600,
        path="/"
    )

    user = await session.get(StaffUser, staff_id)

    return {
        "status": "authenticated",
        "staff_id": staff_id,
        "email": user.email,
        "full_name": user.full_name,
        "tenant_id": membership_obj.tenant_id,
        "tenant_name": tenant_name,
        "role": membership_obj.role,
        "csrf_token": csrf_token,
        "available_tenants": [
            {"tenant_id": m.tenant_id, "name": tname, "role": m.role}
            for m, tname in memberships
        ]
    }


@router.post("/step-up")
async def step_up(req: StepUpRequest, staff=Depends(_current_staff)):
    """Re-authenticate password or TOTP for elevated 5-minute action window."""
    session_id = staff.session_id

    now = datetime.now(timezone.utc)
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        stmt = select(StaffSession).where(
            StaffSession.session_id == session_id,
            StaffSession.active_tenant_id == staff.tenant_id,
            StaffSession.revoked_at == None,
            StaffSession.expires_at > now
        )
        staff_sess = (await session.execute(stmt)).scalars().first()
        if not staff_sess:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session.")

        user = await session.get(StaffUser, staff_sess.staff_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Staff user not found.")

        verified = False
        if req.password and verify_password(user.password_hash, req.password):
            verified = True
        elif req.totp_code and user.mfa_secret and verify_totp(user.mfa_secret, req.totp_code):
            verified = True

        if not verified:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Step-up verification failed. Provide correct password or TOTP code."
            )

        mark_session_stepped_up(session_id, duration_minutes=5)

        # Audit step-up
        audit = AuditEvent(
            event_id=f"AUD-{secrets.token_hex(8)}",
            tenant_id=staff_sess.active_tenant_id,
            actor_id=user.staff_id,
            actor_role="staff",
            action="step_up_reauth",
            resource_type="auth_session",
            resource_id=session_id,
            details={"step_up_ttl_minutes": 5},
            timestamp=now
        )
        session.add(audit)
        return {
            "status": "stepped_up",
            "stepped_up_until": (now + timedelta(minutes=5)).isoformat()
        }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    staff=Depends(_current_staff),
):
    session_id = request.cookies.get("session_id")
    if session_id:
        now = datetime.now(timezone.utc)
        async with get_async_session(tenant_id=staff.tenant_id) as session:
            stmt = update(StaffSession).where(
                StaffSession.session_id == session_id,
                StaffSession.active_tenant_id == staff.tenant_id,
            ).values(revoked_at=now)
            await session.execute(stmt)
        if session_id in _step_up_tracker:
            del _step_up_tracker[session_id]

    response.delete_cookie(key="session_id", path="/")
    return {"status": "logged_out"}


@router.get("/sessions")
async def list_staff_sessions(
    staff=Depends(_admin_staff),
):
    """List active sessions for the current tenant; session identifiers are truncated by the UI."""
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        result = await session.execute(
            select(StaffSession)
            .where(
                StaffSession.active_tenant_id == staff.tenant_id,
                StaffSession.revoked_at.is_(None),
                StaffSession.expires_at > datetime.now(timezone.utc),
            )
            .order_by(StaffSession.created_at.desc())
        )
        sessions = result.scalars().all()
        return [
            {
                "session_id": item.session_id,
                "staff_id": item.staff_id,
                "active_tenant_id": item.active_tenant_id,
                "created_at": item.created_at.isoformat(),
                "expires_at": item.expires_at.isoformat(),
            }
            for item in sessions
        ]


@router.delete("/sessions/{session_id}")
async def revoke_staff_session(
    session_id: str,
    staff=Depends(_admin_staff),
):
    """Revoke an active session only within the admin's tenant."""
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        result = await session.execute(
            update(StaffSession)
            .where(
                StaffSession.session_id == session_id,
                StaffSession.active_tenant_id == staff.tenant_id,
                StaffSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Active staff session not found.")
    _step_up_tracker.pop(session_id, None)
    return {"status": "revoked", "session_id": session_id}


class CreateStaffUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # 'executive', 'manager', 'admin'
    tenant_id: Optional[str] = None


class CreateTenantRequest(BaseModel):
    tenant_id: str
    name: str
    owner_email: EmailStr
    owner_name: str
    owner_password: str


@router.get("/staff")
async def list_staff_users(
    staff=Depends(_admin_staff),
):
    """Admin-only endpoint to list all staff users and their roles for the current tenant."""
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        stmt = (
            select(StaffUser, StaffTenantMembership)
            .join(StaffTenantMembership, StaffUser.staff_id == StaffTenantMembership.staff_id)
            .where(StaffTenantMembership.tenant_id == staff.tenant_id)
            .order_by(StaffUser.created_at.desc())
        )
        rows = (await session.execute(stmt)).all()
        return [
            {
                "staff_id": user.staff_id,
                "email": user.email,
                "full_name": user.full_name,
                "role": membership.role,
                "tenant_id": membership.tenant_id,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
            for user, membership in rows
        ]


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(req: CreateTenantRequest, request: Request, staff=Depends(_admin_staff)):
    """Create an isolated tenant and its initial administrator in one transaction."""
    tenant_id = req.tenant_id.strip().lower()
    name = req.name.strip()
    owner_name = req.owner_name.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,63}", tenant_id):
        raise HTTPException(status_code=400, detail="Tenant ID must be 3–64 lowercase letters, numbers, hyphens, or underscores.")
    if not name or len(name) > 255 or not owner_name or len(owner_name) > 255:
        raise HTTPException(status_code=400, detail="Tenant and administrator names are required and must be 255 characters or fewer.")
    if len(req.owner_password) < 12:
        raise HTTPException(status_code=400, detail="Initial administrator password must be at least 12 characters.")
    async with get_async_session(tenant_id=staff.tenant_id) as session:
        if await session.get(Tenant, tenant_id):
            raise HTTPException(status_code=409, detail="Tenant ID already exists.")
        if (await session.execute(select(StaffUser).where(StaffUser.email == req.owner_email))).scalars().first():
            raise HTTPException(status_code=409, detail="An account with that email already exists.")
        now = datetime.now(timezone.utc)
        owner_id = f"staff_admin_{secrets.token_hex(5)}"
        owner = StaffUser(staff_id=owner_id, email=req.owner_email, full_name=owner_name,
                          password_hash=hash_password(req.owner_password), created_at=now)
        session.add(Tenant(tenant_id=tenant_id, name=name, widget_config={
            "name": "NovaRetail Support", "greeting": "Hi! How can I help you today?", "primaryColor": "#0284c7",
            "theme": "light", "launcherSide": "right", "quickPrompts": ["Track my order", "Product questions"], "autoOpen": False,
        }))
        session.add(owner)
        await session.flush()
        if session.bind.dialect.name == "postgresql":
            await session.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant_id})
            await session.execute(text("SELECT set_config('app.staff_id', :staff, true)"), {"staff": staff.staff_id})
        session.add(StaffTenantMembership(id=f"mem_{owner_id}_{tenant_id}", staff_id=owner_id,
                                          tenant_id=tenant_id, role="admin", created_at=now))
        session.add(AuditEvent(event_id=f"AUD-{secrets.token_hex(8)}", tenant_id=tenant_id,
                               actor_id=staff.staff_id, actor_role=staff.role, action="create_tenant",
                               resource_type="tenant", resource_id=tenant_id,
                               details={"name": name, "owner_email": req.owner_email}, timestamp=now,
                               ip_address=request.client.host if request.client else None))
    return {"tenant_id": tenant_id, "name": name, "admin_email": req.owner_email, "admin_staff_id": owner_id}


@router.post("/staff")
async def create_staff_user(
    req: CreateStaffUserRequest,
    staff=Depends(_admin_staff),
):
    """Admin-only endpoint to provision new executives, managers, or admins."""
    if req.role not in ("executive", "manager", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{req.role}'. Allowed roles: executive, manager, admin."
        )

    target_tenant = req.tenant_id or staff.tenant_id
    now = datetime.now(timezone.utc)

    async with get_async_session(tenant_id=staff.tenant_id) as session:
        # Check if email already exists
        existing = (await session.execute(
            select(StaffUser).where(StaffUser.email == req.email)
        )).scalars().first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Staff user with email '{req.email}' already exists."
            )

        new_staff_id = f"staff_{req.role[:3]}_{secrets.token_hex(4)}"
        new_user = StaffUser(
            staff_id=new_staff_id,
            email=req.email,
            full_name=req.full_name,
            password_hash=hash_password(req.password),
            created_at=now,
        )
        session.add(new_user)
        await session.flush()

        membership = StaffTenantMembership(
            id=f"mem_{new_staff_id}_{target_tenant}",
            staff_id=new_staff_id,
            tenant_id=target_tenant,
            role=req.role,
            created_at=now,
        )
        session.add(membership)

        audit = AuditEvent(
            event_id=f"AUD-{secrets.token_hex(8)}",
            tenant_id=target_tenant,
            actor_id=staff.staff_id,
            actor_role=staff.role,
            action="create_staff_user",
            resource_type="staff_user",
            resource_id=new_staff_id,
            details={"email": req.email, "role": req.role, "tenant_id": target_tenant},
            timestamp=now,
        )
        session.add(audit)

    return {
        "status": "created",
        "staff_id": new_staff_id,
        "email": req.email,
        "full_name": req.full_name,
        "role": req.role,
        "tenant_id": target_tenant,
    }
