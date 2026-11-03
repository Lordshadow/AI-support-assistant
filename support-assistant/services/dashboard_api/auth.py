"""
Staff Authentication & Identity Service (Spec 15.1.8).
Argon2id hashing, RFC 6238 TOTP MFA, opaque server-side sessions, and double-submit CSRF.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import secrets
from typing import Optional, Dict, Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
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

    async with get_async_session() as session:
        stmt = select(StaffUser).where(StaffUser.email == email_clean)
        user = (await session.execute(stmt)).scalars().first()

        # Constant-time mitigation against timing attacks if user not found
        dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$5W2O/G/m0kZ7P5yJ3M342mK6"
        target_hash = user.password_hash if user else dummy_hash

        if user and user.locked_until and user.locked_until > now:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is temporarily locked due to failed attempts. Please try again later."
            )

        if not verify_password(target_hash, req.password) or not user:
            if user:
                user.failed_attempts += 1
                if user.failed_attempts >= 5:
                    user.locked_until = now + timedelta(minutes=15)
                await session.flush()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Successful password verification: reset failed attempts
        user.failed_attempts = 0
        user.locked_until = None
        await session.flush()

        # If user has MFA enrolled, issue short-lived MFA ticket
        if user.mfa_secret:
            ticket = f"mfa_{secrets.token_urlsafe(32)}"
            _mfa_tickets[ticket] = {
                "staff_id": user.staff_id,
                "email": user.email,
                "preferred_tenant": req.tenant_id,
                "expires_at": now + timedelta(minutes=5),
            }
            return {
                "status": "mfa_required",
                "mfa_ticket": ticket,
                "message": "Enter your 6-digit authenticator code."
            }

        # If no MFA (e.g. bootstrap / non-enrolled staff), establish session directly
        return await _create_staff_session(user.staff_id, req.tenant_id, response, session)


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

    # 2. Generate opaque session ID and CSRF token
    session_id = f"sess_{secrets.token_urlsafe(32)}"
    csrf_token = secrets.token_urlsafe(32)
    csrf_hash = hashlib.sha256(csrf_token.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(hours=8)

    db_sess = StaffSession(
        session_id=session_id,
        staff_id=staff_id,
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
    await session.flush()

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
async def step_up(req: StepUpRequest, request: Request):
    """Re-authenticate password or TOTP for elevated 5-minute action window."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Active session required.")

    now = datetime.now(timezone.utc)
    async with get_async_session() as session:
        stmt = select(StaffSession).where(
            StaffSession.session_id == session_id,
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
        await session.flush()

        return {
            "status": "stepped_up",
            "stepped_up_until": (now + timedelta(minutes=5)).isoformat()
        }


@router.post("/logout")
async def logout(request: Request, response: Response):
    session_id = request.cookies.get("session_id")
    if session_id:
        now = datetime.now(timezone.utc)
        async with get_async_session() as session:
            stmt = update(StaffSession).where(StaffSession.session_id == session_id).values(revoked_at=now)
            await session.execute(stmt)
            await session.flush()

        if session_id in _step_up_tracker:
            del _step_up_tracker[session_id]

    response.delete_cookie(key="session_id", path="/")
    return {"status": "logged_out"}
