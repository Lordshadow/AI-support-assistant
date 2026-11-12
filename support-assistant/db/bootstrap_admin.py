"""Safely create the first production dashboard administrator.

Credentials are supplied at runtime through environment variables (ideally
Cloud Run Job Secret Manager references). Existing accounts are never reset.
"""

import asyncio
import os
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import StaffTenantMembership, StaffUser, Tenant
from db.session import get_async_session
from services.dashboard_api.auth import hash_password


async def bootstrap_admin() -> None:
    email = os.environ["BOOTSTRAP_ADMIN_EMAIL"].strip().lower()
    password = os.environ["BOOTSTRAP_ADMIN_PASSWORD"]
    full_name = os.environ["BOOTSTRAP_ADMIN_NAME"].strip()
    tenant_id = os.getenv("NOVARETAIL_TENANT_ID", "tenant_novaretail").strip()

    if len(password) < 16:
        raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must be at least 16 characters.")
    if not email or not full_name or not tenant_id:
        raise ValueError("Admin email, full name, and tenant ID must not be blank.")

    now = datetime.now(timezone.utc)
    # RLS on staff_tenant_memberships requires the target tenant context even
    # for the initial membership row. Set it for this transaction before writes.
    async with get_async_session(tenant_id=tenant_id) as session:
        existing = (
            await session.execute(select(StaffUser).where(StaffUser.email == email))
        ).scalars().first()
        if existing:
            raise RuntimeError(
                "That staff email already exists; bootstrap will not change its password or role."
            )

        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            tenant = Tenant(
                tenant_id=tenant_id,
                name="NovaRetail Enterprise",
                daily_spend_cap_inr=2500,
                monthly_spend_cap_inr=50000,
                spend_mode="normal",
                created_at=now,
            )
            session.add(tenant)
            await session.flush()

        staff_id = f"staff_admin_{secrets.token_hex(8)}"
        session.add(
            StaffUser(
                staff_id=staff_id,
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                created_at=now,
            )
        )
        # The ORM models intentionally avoid cross-tenant relationships; flush
        # the parent explicitly before inserting the FK-dependent membership.
        await session.flush()
        session.add(
            StaffTenantMembership(
                id=f"mem_{staff_id}_{tenant_id}",
                staff_id=staff_id,
                tenant_id=tenant_id,
                role="admin",
                created_at=now,
            )
        )

    print(f"Created initial admin {email} for tenant {tenant_id}.")


if __name__ == "__main__":
    asyncio.run(bootstrap_admin())
