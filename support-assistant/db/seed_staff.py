"""
Seed default staff accounts and tenant memberships.
Idempotent script to bootstrap default Master Control Dashboard credentials.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from db.models import Tenant, StaffUser, StaffTenantMembership
from db.session import get_async_session
from services.dashboard_api.auth import hash_password

SEEDED_TENANTS = [
    {
        "tenant_id": "demo-shop",
        "name": "NovaRetail Demo Store",
        "daily_spend_cap_inr": 2500,
        "monthly_spend_cap_inr": 50000,
    },
    {
        "tenant_id": "tenant_novaretail",
        "name": "NovaRetail Enterprise",
        "daily_spend_cap_inr": 2500,
        "monthly_spend_cap_inr": 50000,
    }
]

SEEDED_STAFF = [
    {
        "staff_id": "staff_admin_01",
        "email": "admin@novaretail.com",
        "full_name": "System Administrator",
        "password": "AdminPassword123!",
        "role": "admin",
    },
    {
        "staff_id": "staff_manager_01",
        "email": "manager@novaretail.com",
        "full_name": "Operations Manager",
        "password": "ManagerPassword123!",
        "role": "manager",
    },
    {
        "staff_id": "staff_executive_01",
        "email": "executive@novaretail.com",
        "full_name": "Support Executive",
        "password": "ExecutivePassword123!",
        "role": "executive",
    },
]


async def seed_staff():
    print("Seeding default tenants and staff users...")
    now = datetime.now(timezone.utc)

    async with get_async_session() as session:
        # 1. Seed Tenants
        for t_data in SEEDED_TENANTS:
            existing_t = await session.get(Tenant, t_data["tenant_id"])
            if not existing_t:
                tenant = Tenant(
                    tenant_id=t_data["tenant_id"],
                    name=t_data["name"],
                    daily_spend_cap_inr=t_data["daily_spend_cap_inr"],
                    monthly_spend_cap_inr=t_data["monthly_spend_cap_inr"],
                    spend_mode="normal",
                    created_at=now,
                )
                session.add(tenant)
                print(f"Created tenant: {t_data['tenant_id']} ({t_data['name']})")

        # 2. Seed Staff Accounts & Memberships
        for s_data in SEEDED_STAFF:
            stmt = select(StaffUser).where(StaffUser.email == s_data["email"])
            existing_user = (await session.execute(stmt)).scalars().first()

            if not existing_user:
                user = StaffUser(
                    staff_id=s_data["staff_id"],
                    email=s_data["email"],
                    full_name=s_data["full_name"],
                    password_hash=hash_password(s_data["password"]),
                    mfa_secret=None,  # Direct password login enabled by default
                    failed_attempts=0,
                    locked_until=None,
                    created_at=now,
                )
                session.add(user)
                await session.flush()
                print(f"Created staff user: {s_data['email']} (role: {s_data['role']})")

                # Add membership for both demo-shop and tenant_novaretail
                for t_data in SEEDED_TENANTS:
                    membership = StaffTenantMembership(
                        id=f"mem_{s_data['staff_id']}_{t_data['tenant_id']}",
                        staff_id=s_data["staff_id"],
                        tenant_id=t_data["tenant_id"],
                        role=s_data["role"],
                        created_at=now,
                    )
                    session.add(membership)
            else:
                # Update password hash to guarantee known default password
                existing_user.password_hash = hash_password(s_data["password"])
                existing_user.failed_attempts = 0
                existing_user.locked_until = None
                print(f"Reset password for staff user: {s_data['email']}")

        await session.commit()
    print("Staff and tenant seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed_staff())
